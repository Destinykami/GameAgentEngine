"""反思双流隔离与触发器按流回归 (F1-2 / F1-3)。

- `_save` 的去重池必须按流: 自我/身份反思只与共享流比, 关系反思只与该玩家面比。
  `all_valid(player_id=None)` 是"不过滤"而非共享流 (E2 陷阱), 不能再把两者混在
  一起。
- `_importance_accum` 是**自我反思**触发器, 只由共享流观察累加; 关系观察走
  `speak`/`flush_social` 的 `_reflected_obs` 门控。
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from persona_agent import NPC
from persona_agent.embeddings import HashEmbedder
from tests.test_persistence import _StubLLM, TRAITS


def _npc() -> NPC:
    return NPC("测试人", dict(TRAITS), llm=_StubLLM(),
               embedder=HashEmbedder())


# ---------------------------------------------------------------- F1-2 去重池
def test_relationship_reflection_does_not_dedup_self_reflection():
    """关系面已有同义反思时, 共享自我反思仍应入库 (旧实现被跨流去重吞掉)。"""
    npc = _npc()
    npc.observe("Aria 帮过我", 1.0, player_id="Aria")
    npc.reflect_relationship("Aria", 2.0)
    rel = npc.store.all_valid(player_id="Aria", types=["reflection"])
    assert len(rel) == 1

    npc.observe("镇上今天很安静", 3.0)   # 共享流
    ids = npc.reflection.reflect_self(npc.store, 4.0)
    shared = npc.store.all_valid(shared=True, types=["reflection"])
    assert ids and len(shared) == 1, \
        "共享自我反思不得被关系反思的 0.92 去重池吞掉"
    assert shared[0].player_id is None
    assert rel[0].valid, "关系反思仍应有效"


def test_self_reflection_does_not_dedup_relationship_reflection():
    """反向: 共享自我反思已有同义内容时, 关系反思仍应入库。"""
    npc = _npc()
    npc.observe("镇上今天很安静", 1.0)
    npc.reflection.reflect_self(npc.store, 2.0)
    assert len(npc.store.all_valid(shared=True, types=["reflection"])) == 1

    npc.observe("Aria 帮过我", 3.0, player_id="Aria")
    ids = npc.reflect_relationship("Aria", 4.0)
    rel = npc.store.all_valid(player_id="Aria", types=["reflection"])
    assert ids and len(rel) == 1, "关系反思不得被共享自我反思去重吞掉"
    assert rel[0].player_id == "Aria"


def test_same_stream_dedup_still_works():
    """同一流内仍然去重: 重复跑 reflect_self 不重复入库同义洞察。"""
    npc = _npc()
    npc.observe("镇上今天很安静", 1.0)
    first = npc.reflection.reflect_self(npc.store, 2.0)
    second = npc.reflection.reflect_self(npc.store, 3.0)
    assert first and not second, "同流同义洞察应被去重"
    assert len(npc.store.all_valid(shared=True, types=["reflection"])) == 1


# ---------------------------------------------------------------- F1-3 触发器
def test_relation_observations_do_not_accumulate_self_trigger():
    """31 条关系观察不得把 self 触发器打满 (旧实现 accum=155 后空转清零)。"""
    npc = _npc()
    for i in range(31):
        npc.observe(f"player event unique{i} alpha{i}", float(i),
                    player_id="P")
    assert npc._importance_accum == 0.0, \
        "关系观察不应累积自我反思触发器"
    assert npc.maybe_reflect_self(40.0) == []
    assert npc._importance_accum == 0.0


def test_shared_observations_still_trigger_self_reflection():
    """共享流观察照常累积, 过阈值后产出共享反思。"""
    npc = _npc()
    for i in range(31):
        npc.observe(f"shared event unique{i} alpha{i}", float(i))
    assert npc._importance_accum == 155.0
    ids = npc.maybe_reflect_self(40.0)
    assert ids, "共享观察超过阈值后应触发自我反思"
    assert npc._importance_accum == 0.0
    assert npc.store.all_valid(shared=True, types=["reflection"])


def test_one_shared_observation_not_re_reflected_by_relation_batches():
    """只有 1 条共享观察时, 多批关系观察不得反复触发自我反思。"""
    class _CountingLLM(_StubLLM):
        def __init__(self) -> None:
            super().__init__()
            self.question_calls = 0

        def reflection_questions(self, recent):
            self.question_calls += 1
            return super().reflection_questions(recent)

    llm = _CountingLLM()
    npc = NPC("测试人", dict(TRAITS), llm=llm, embedder=HashEmbedder())
    npc.observe("shared event unique0 alpha0", 0.0)
    for batch in range(3):
        for i in range(31):
            npc.observe(f"p{batch} event unique{i} beta{i}",
                        float(batch * 40 + i + 1), player_id="P")
        assert npc.maybe_reflect_self(float(batch * 40 + 40)) == []
    assert llm.question_calls == 0, "关系观察批次不应触发自我反思"
    assert npc._importance_accum == 5.0
