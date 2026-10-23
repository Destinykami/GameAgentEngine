"""P2 世界运行时状态回归 (F6-4/F6-5/F6-6/F6-7)。"""

from __future__ import annotations

import os


from game_agent import Location, MemoryRecord, NPC, World
from tests.test_persistence import _StubLLM, TRAITS


def _world(tmp_path) -> World:
    w = World("w", [Location("L", 0, 0)])
    w.add_npc("A", dict(TRAITS), llm=_StubLLM(),
              data_dir=str(tmp_path / "A"), location="L")
    w.add_npc("B", dict(TRAITS), llm=_StubLLM(),
              data_dir=str(tmp_path / "B"), location="L")
    return w


def test_new_observations_counts_only_inserts(tmp_path):
    w = _world(tmp_path)
    w.add_player("P", "L")
    first = w.step(1.0)
    assert first["new_observations"].get("A") == 1
    second = w.step(2.0)   # 同一在场观察走 merge, 不新增
    assert "A" not in second["new_observations"]
    w.close()


class _BoomPerceive(_StubLLM):
    def perceive_action(self, *args, **kwargs):
        raise RuntimeError("perceive down")


def test_chain_rule_does_not_advance_on_failed_action(tmp_path):
    w = World("w", [Location("L", 0, 0)])
    w.add_chain_rule("attack", 2, "chain fired")
    w.add_npc("A", dict(TRAITS), llm=_StubLLM(),
              data_dir=str(tmp_path / "A"), location="L")
    w.add_npc("B", dict(TRAITS), llm=_BoomPerceive(),
              data_dir=str(tmp_path / "B"), location="L")
    for _ in range(2):
        w.execute_action(w.get("A"), {"action": "attack", "target": "B"})
    assert not any(v.type == "world_event" for v in w.visual_events), \
        "失败动作不应推进行为链"
    w.close()


def test_chain_rule_advances_on_success(tmp_path):
    w = World("w", [Location("L", 0, 0)])
    w.add_chain_rule("attack", 2, "chain fired")
    w.add_npc("A", dict(TRAITS), llm=_StubLLM(),
              data_dir=str(tmp_path / "A"), location="L")
    w.add_npc("B", dict(TRAITS), llm=_StubLLM(),
              data_dir=str(tmp_path / "B"), location="L")
    for _ in range(2):
        w.execute_action(w.get("A"), {"action": "attack", "target": "B"})
    assert any(v.type == "world_event" for v in w.visual_events), \
        "连续成功攻击应触发行为链"
    w.close()


def test_flee_threat_filter(tmp_path):
    w = _world(tmp_path)
    a = w.get("A")
    w.threat_filter = lambda agent, other: False
    out = w.execute_action(a, {"action": "flee"})
    assert "无威胁" in out
    w.threat_filter = None
    out2 = w.execute_action(a, {"action": "flee"})
    assert w.visual_events[-1].success is True
    assert "逃离威胁" in out2
    w.close()


def test_npc_transient_state_roundtrip(tmp_path):
    npc = NPC.create("T", dict(TRAITS), llm=_StubLLM(),
                     data_dir=str(tmp_path))
    for index in range(3):
        npc.store.add(MemoryRecord(f"P 的观察 {index}", 1.0, player_id="P"))
    npc.maybe_reflect_relationship("P", 12.0)
    npc.plan_state.replace([(7, 9, "写代码")])
    npc.save()
    npc2 = NPC.load(os.path.join(str(tmp_path), "T.db"), llm=_StubLLM())
    assert npc2.runtime_state().reflected_obs == {"P": 3}
    assert npc2.plan_state.blocks == [(7, 9, "写代码")]
    assert npc2.runtime_state().last_sweep == 12.0


def test_world_day_anchors_roundtrip(tmp_path):
    path = str(tmp_path / "world.db")
    w = World("w", [Location("L", 0, 0)], path=path)
    w.add_npc("A", dict(TRAITS), llm=_StubLLM(),
              data_dir=str(tmp_path / "A"), location="L")
    w._last_plan_day = 2
    w._last_consolidate_day = 1
    w.save()
    w.close()
    w2 = World("w", [Location("L", 0, 0)], path=path)
    w2.load(llm=_StubLLM())
    assert w2._last_plan_day == 2
    assert w2._last_consolidate_day == 1
    w2.close()
