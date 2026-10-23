"""置信度衰减与消费测试 (H1 + H2 回归)。

H1 幂等衰减: 目标水位 = base_confidence * 0.5**(不同冲突观察条数)。
    同一组证据重跑 check_conflicts 不再折半; 一条新冲突观察恰好多折半一次。
H2 置信度有下游消费者:
    - 检索评分按 confidence 折减 (削弱的反思排名下降, 甚至跌出观察);
    - judge_trust 收到 (类型, 内容, 置信度) 三元组;
    - 对话 prompt 对被削弱的反思显式标注置信度。
无网络, stub LLM。
"""

from __future__ import annotations


import pytest


from game_agent import MemoryRecord, MemoryStore
from game_agent.models.embeddings import HashEmbedder
from game_agent.models.llm import LLMContext
from game_agent.models.llm_http import RealLLM
from game_agent.cognition.reacting import ReactionDecider
from game_agent.cognition.reflection import ReflectionEngine
from tests.test_persistence import _StubLLM

REF_CONTENT = "Aria 是值得信赖的伙伴"


class ConflictLLM(_StubLLM):
    """judge_conflict 恒返回给定强度 (离线确定性的矛盾判定)。"""

    def __init__(self, severity: int) -> None:
        super().__init__()
        self._severity = severity

    def judge_conflict(self, reflection, observation):
        return self._severity


def _store_with_conflict(severity: int):
    """一个反思 (base 0.8) + 一条更晚的矛盾观察, 返回 (store, engine, ref_id)。"""
    store = MemoryStore(HashEmbedder())
    obs_id = store.add(MemoryRecord(
        content="Aria 背叛了 Klaus, 拿走了咖啡豆", timestamp=2.0,
        type="observation", player_id="Aria", importance=8.0))
    ref_id = store.add(MemoryRecord(
        content=REF_CONTENT, timestamp=1.0, type="reflection",
        player_id="Aria", evidence=[obs_id], confidence=0.8,
        base_confidence=0.8))
    engine = ReflectionEngine(ConflictLLM(severity), HashEmbedder())
    return store, engine, ref_id


def _conf(store, ref_id) -> float:
    return store.all_valid(player_id="Aria", types=["reflection"])[0].confidence


def test_decay_idempotent():
    """同一组证据重跑 check_conflicts: 折半一次后水位不再下降。"""
    store, engine, ref_id = _store_with_conflict(severity=5)
    engine.check_conflicts(store, "Aria", now=3.0)
    assert _conf(store, ref_id) == pytest.approx(0.4), "一条冲突证据折半一次"
    engine.check_conflicts(store, "Aria", now=4.0)
    assert _conf(store, ref_id) == pytest.approx(0.4), \
        "同一证据重跑不得再折半 (旧实现: 0.4→0.2→...)"
    engine.check_conflicts(store, "Aria", now=5.0)
    assert _conf(store, ref_id) == pytest.approx(0.4)


def test_new_conflict_observation_halves_again():
    """一条**新的**冲突观察出现: 水位恰好多折半一次 (0.4→0.2)。"""
    store, engine, ref_id = _store_with_conflict(severity=5)
    engine.check_conflicts(store, "Aria", now=3.0)
    assert _conf(store, ref_id) == pytest.approx(0.4)
    store.add(MemoryRecord(
        content="Aria 再次爽约, 没有赴约", timestamp=3.5,
        type="observation", player_id="Aria", importance=7.0))
    engine.check_conflicts(store, "Aria", now=4.0)
    assert _conf(store, ref_id) == pytest.approx(0.2), \
        "新证据 k=2 → base*0.5^2 = 0.2"


def test_strong_conflict_invalidates_not_decays():
    """强矛盾 (severity≥7): 直接失效, 置信度不动。"""
    store, engine, ref_id = _store_with_conflict(severity=8)
    engine.check_conflicts(store, "Aria", now=3.0)
    assert ref_id not in {m.id for m in store.all_valid(player_id="Aria")}, \
        "强矛盾反思应失效"
    invalid = {m.id: m for m in store.all_invalid()}
    assert invalid[ref_id].confidence == pytest.approx(0.8), \
        "失效路径不应改写置信度"


def test_retrieval_score_damped_by_confidence():
    """检索评分按 confidence 折减: 同样内容, conf 0.5 的反思得分恰为 1.0 的一半,
    且跌落到同权重观察之下 (削弱的信念排名下降)。"""
    def build(ref_conf: float) -> MemoryStore:
        s = MemoryStore(HashEmbedder())
        s.add(MemoryRecord(content="Aria 帮 Klaus 修好了咖啡机", timestamp=1.0,
                           type="observation", importance=5.0))
        s.add(MemoryRecord(content="Aria 帮 Klaus 修好了咖啡机", timestamp=2.0,
                           type="reflection", importance=5.0,
                           confidence=ref_conf))
        return s

    res_full = build(1.0).retrieve("咖啡机", now=10.0)
    res_damped = build(0.5).retrieve("咖啡机", now=10.0)
    by_type = lambda res: {m["type"]: m["score"] for m in res}
    s_full, s_damped = by_type(res_full), by_type(res_damped)
    assert s_damped["reflection"] == pytest.approx(
        s_full["reflection"] * 0.5), "折减是精确的 confidence 乘法"
    assert s_damped["reflection"] < s_damped["observation"], \
        "被削弱的反思排名应跌到观察之下"
    assert s_full["reflection"] > s_full["observation"], "对照组: 满置信反思在观察之上"


class RecordingTrustLLM(_StubLLM):
    def __init__(self) -> None:
        super().__init__()
        self.received: list[tuple] | None = None

    def judge_trust(self, memories, player_id):
        self.received = memories
        return 0.5


def test_judge_trust_receives_confidence():
    """judge_trust 收到 (类型, 内容, 置信度) 三元组, 削弱的反思带着衰减后的值。"""
    store = MemoryStore(HashEmbedder())
    obs_id = store.add(MemoryRecord(
        content="Aria 帮 Klaus 修好了咖啡机", timestamp=1.0,
        type="observation", player_id="Aria", importance=7.0))
    store.add(MemoryRecord(
        content="Aria 值得信赖", timestamp=2.0, type="reflection",
        player_id="Aria", evidence=[obs_id], confidence=0.4))
    llm = RecordingTrustLLM()
    ReactionDecider(store, llm).relationship_trust("Aria")
    assert llm.received is not None
    kinds = {t: conf for t, _c, conf in llm.received}
    assert kinds["reflection"] == pytest.approx(0.4), "反思应带衰减后的置信度"
    assert kinds["observation"] == pytest.approx(1.0), "观察恒 1.0"


class CapturingChatLLM(RealLLM):
    def __init__(self) -> None:
        super().__init__()
        self.prompts: list[str] = []

    def _chat(self, system, user, **kw):
        self.prompts.append(user)
        return "reply"


def test_dialogue_prompt_notes_weakened_reflection():
    """对话 prompt: 被削弱的反思显式标注置信度; 观察 (恒 1.0) 不标注。"""
    llm = CapturingChatLLM()
    llm.complete(LLMContext(
        player_id="Aria", question="你还信任 Aria 吗?",
        memories=[
            {"type": "reflection", "content": "Aria 值得信赖",
             "confidence": 0.4},
            {"type": "observation", "content": "Aria 给了咖啡豆",
             "confidence": 1.0},
        ]))
    prompt = llm.prompts[-1]
    assert "(置信度0.40)" in prompt, "削弱的反思应标注置信度"
    assert "(置信度1.00)" not in prompt, "观察不应被标注 (避免注水)"
