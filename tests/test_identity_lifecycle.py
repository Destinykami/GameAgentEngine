"""身份层/ episode 生命周期与共享冲突回归 (F4-3 / F4-4 / F4-5)。"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from persona_agent import Location, MemoryRecord, MemoryStore, NPC, World
from persona_agent.embeddings import HashEmbedder
from tests.test_persistence import _StubLLM, TRAITS


# ---------------------------------------------------------------- F4-3 半衰期
def test_identity_and_episode_half_lives():
    store = MemoryStore(HashEmbedder())
    for rtype in ("observation", "reflection", "episode", "identity"):
        store.add(MemoryRecord(content=f"{rtype} unique content",
                               timestamp=0.0, type=rtype, importance=8.0))
    store.decay_and_forget(now=48.0)   # 一个 observation 半衰期
    vals = {m.type: m.importance for m in store.all_valid()}
    assert vals["episode"] > vals["observation"], "episode 应比原始观察留存更久"
    assert vals["identity"] > vals["episode"], "identity 应比 episode 更稳定"
    assert vals["identity"] == pytest.approx(8.0 * 0.5 ** (48.0 / 336.0))


# ---------------------------------------------------------------- F4-4 身份生成
def _world(tmp_path, **flags) -> World:
    w = World("w", [Location("L", 0, 0)], consolidation=True,
              consolidate_hour=23.0, **flags)
    w.add_npc("A", dict(TRAITS), llm=_StubLLM(),
              data_dir=str(tmp_path / "A"), location="L")
    return w


def _seed_shared(npc: NPC) -> None:
    npc.observe("镇上来了眼狩队", 10.0)
    npc.observe("眼狩署方向冒烟", 11.0)


def test_identity_generated_when_flag_on(tmp_path):
    w = _world(tmp_path, use_identity_beliefs=True)
    _seed_shared(w.npc("A"))
    w.step(23.0)
    ident = w.npc("A").store.all_valid(shared=True, types=["identity"])
    assert ident, "use_identity_beliefs=True 时固化节拍应生成 identity"
    assert ident[0].player_id is None
    w.close()


def test_identity_not_generated_when_flag_off(tmp_path):
    w = _world(tmp_path, use_identity_beliefs=False)
    _seed_shared(w.npc("A"))
    w.step(23.0)
    assert not w.npc("A").store.all_valid(shared=True, types=["identity"])
    w.close()


# ---------------------------------------------------------------- F4-5 共享冲突
class _ConflictLLM(_StubLLM):
    def judge_conflict(self, reflection, observation):
        if "信任" in reflection and "背叛" in observation:
            return 9
        return 0


def test_shared_self_reflection_can_be_invalidated():
    npc = NPC("测试人", dict(TRAITS), llm=_ConflictLLM(),
              embedder=HashEmbedder())
    ref_id = npc.store.add(MemoryRecord(
        content="我信任外来者", timestamp=1.0, type="reflection",
        player_id=None, confidence=0.8))
    npc.observe("外来者背叛了我", 2.0)
    handled = npc.reflection.check_conflicts(npc.store, None, 3.0, shared=True)
    assert ref_id in handled
    invalid = {m.id for m in npc.store.all_invalid()}
    assert ref_id in invalid, "共享自我反思应被更晚的世界观察推翻"


def test_shared_conflicts_run_on_self_reflection_trigger():
    npc = NPC("测试人", dict(TRAITS), llm=_ConflictLLM(),
              embedder=HashEmbedder())
    ref_id = npc.store.add(MemoryRecord(
        content="我信任外来者", timestamp=0.0, type="reflection",
        player_id=None, confidence=0.8))
    npc.observe("外来者背叛了我", 1.0)
    npc._importance_accum = npc._reflection_threshold   # 强制触发一次自我反思
    npc.maybe_reflect_self(2.0)
    assert ref_id in {m.id for m in npc.store.all_invalid()}, \
        "maybe_reflect_self 应顺带跑共享冲突检查"


def test_shared_identity_can_be_invalidated():
    npc = NPC("测试人", dict(TRAITS), llm=_ConflictLLM(),
              embedder=HashEmbedder())
    ident_id = npc.store.add(MemoryRecord(
        content="我信任外来者", timestamp=1.0, type="identity",
        player_id=None, confidence=0.8))
    npc.observe("外来者背叛了我", 2.0)
    npc.reflection.check_conflicts(npc.store, None, 3.0, shared=True)
    assert ident_id in {m.id for m in npc.store.all_invalid()}, \
        "identity 信念也应参与共享冲突扫描"


class _CountingConflict(_ConflictLLM):
    def __init__(self) -> None:
        super().__init__()
        self.calls = 0

    def judge_conflict(self, reflection, observation):
        self.calls += 1
        return super().judge_conflict(reflection, observation)


def test_shared_conflicts_are_gated_by_new_evidence():
    llm = _CountingConflict()
    npc = NPC("测试人", dict(TRAITS), llm=llm, embedder=HashEmbedder())
    npc.store.add(MemoryRecord(content="我信任外来者", timestamp=1.0,
                               type="reflection", player_id=None,
                               confidence=0.8))
    npc.observe("外来者来拜访", 2.0)
    npc.check_shared_conflicts(3.0)
    first = llm.calls
    assert first >= 1
    npc.check_shared_conflicts(4.0)
    assert llm.calls == first, "没有新共享证据时不得重复判矛盾"
    npc.store.add(MemoryRecord(content="外来者背叛了我", timestamp=5.0,
                               type="observation", player_id=None))
    npc.check_shared_conflicts(6.0)
    assert llm.calls > first, "新共享证据应触发一次检查"
