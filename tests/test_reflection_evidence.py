"""反思证据编号校验测试 (M8 回归): 洞察引用的证据 id 必须真实存在, 不入库断链。

模型可能回纯顺序号 (1,2,3) 或幻影编号而传入证据的真实 id 是 101/103:
- 真实编号保留; 幻影编号丢弃;
- 全幻影 / 空引用 → 回退全引传入证据 (宁宽勿断链, 一条洞察总得有据可查)。
无网络: 子类化 RealLLM 覆写 _chat_json 直接喂坏输出。
"""

from __future__ import annotations



from game_agent import MemoryRecord, MemoryStore
from game_agent.models.embeddings import HashEmbedder
from game_agent.models.llm_http import RealLLM
from game_agent.cognition.reflection import ReflectionEngine


def _llm_with(data) -> RealLLM:
    class FedLLM(RealLLM):
        def _chat_json(self, system, user, **kw):
            return data
    return FedLLM()


EVIDENCE = [(101, "Aria 帮 Klaus 修好了咖啡机"), (103, "Klaus 感谢 Aria 的照顾")]


def test_real_ids_kept():
    """模型回真实编号: 原样保留。"""
    out = _llm_with([{"insight": "Aria 值得信赖", "evidence": [101, 103]}]
                    ).reflection_insights(EVIDENCE, n=3)
    assert out == [("Aria 值得信赖", [101, 103])]


def test_phantom_ids_fallback_to_all():
    """模型回纯顺序号 (1,2,3) 而真实 id 是 101/103: 回退全引, 不入库幻影 id。"""
    out = _llm_with([{"insight": "Aria 值得信赖", "evidence": [1, 2]}]
                    ).reflection_insights(EVIDENCE, n=3)
    assert out == [("Aria 值得信赖", [101, 103])]


def test_mixed_keeps_only_real():
    """一半真实一半幻影: 只留真实的那部分。"""
    out = _llm_with([{"insight": "Aria 值得信赖", "evidence": [101, 999]}]
                    ).reflection_insights(EVIDENCE, n=3)
    assert out == [("Aria 值得信赖", [101])]


def test_empty_evidence_fallback_to_all():
    """模型漏给 evidence 字段: 回退全引。"""
    out = _llm_with([{"insight": "Aria 值得信赖"}]
                    ).reflection_insights(EVIDENCE, n=3)
    assert out == [("Aria 值得信赖", [101, 103])]


def test_stored_reflection_evidence_all_real():
    """集成: 模型回幻影编号, 走完整 reflect_relationship 入库,
    反思的证据 id 必须全部是库里真实存在的观察 id。"""
    store = MemoryStore(HashEmbedder())
    store.add(MemoryRecord(content="Klaus 擦了桌子", timestamp=0.0,
                           type="observation", player_id=None, importance=2.0))
    store.add(MemoryRecord(content="Klaus 浇了花", timestamp=0.5,
                           type="observation", player_id=None, importance=2.0))
    # Aria 的观察落在 id 3, 4 (非平凡编号, 让幻影 [1,2] 必不重合)
    store.add(MemoryRecord(content="Aria 帮 Klaus 修好了咖啡机", timestamp=1.0,
                           type="observation", player_id="Aria", importance=7.0))
    store.add(MemoryRecord(content="Aria 保护了 Klaus", timestamp=2.0,
                           type="observation", player_id="Aria", importance=7.0))

    class FedReflectionLLM(RealLLM):
        def __init__(self) -> None:
            super().__init__()
            self._queue = iter([
                ["Klaus 和 Aria 的关系如何?"],
                [{"insight": "Aria 值得信赖", "evidence": [1, 2]}],   # 幻影编号
            ])

        def _chat_json(self, system, user, **kw):
            return next(self._queue)

    engine = ReflectionEngine(FedReflectionLLM(), HashEmbedder())
    new_ids = engine.reflect_relationship(store, "Aria", now=3.0)
    assert new_ids, "应生成反思"
    ref = store.all_valid(player_id="Aria", types=["reflection"])[0]
    obs_ids = {m.id for m in store.all_valid(player_id="Aria", types=["observation"])}
    assert obs_ids == {3, 4}
    assert set(ref.evidence) <= obs_ids, \
        f"证据 id 必须全部真实存在 (断链入库), 实际 {ref.evidence}"
    assert sorted(ref.evidence) == [3, 4], \
        "全幻影引用应回退为全引传入证据 (Aria 的两条观察; 顺序随检索分数, 不比序)"
