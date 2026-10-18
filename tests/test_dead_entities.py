"""死亡语义回归 (F3-1)。

死者不驱动档位、不感知、不被感知; `step` 不再让死 NPC 继续认知。
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from persona_agent import Location, World
from tests.test_persistence import _StubLLM, TRAITS


def _world(tmp_path) -> World:
    w = World("w", [Location("近", 0, 0), Location("远", 100, 100)])
    w.add_npc("A", dict(TRAITS), llm=_StubLLM(),
              data_dir=str(tmp_path / "A"), location="近")
    return w


def test_dead_player_does_not_drive_tier_or_perception(tmp_path):
    w = _world(tmp_path)
    p = w.add_player("P", "近")
    assert w.tier_of("A") == "full"
    p.dead = True
    p.health = 0
    assert w.tier_of("A") == "idle", "死者不应让 NPC 保持 full 档"
    assert w.perceive("A", 1.0) == []
    assert w.npc("A").store.all_valid(player_id="P", types=["observation"]) == []
    w.close()


def test_dead_npc_skips_step_and_tier(tmp_path):
    w = _world(tmp_path)
    w.add_player("P", "近")
    a = w.get("A")
    a.dead = True
    a.health = 0
    assert w.tier_of("A") == "idle"
    res = w.step(1.0)
    assert "A" not in res["new_observations"]
    assert w.npc("A").store.all_valid() == [], "死 NPC 不应在 step 中继续感知"
    w.close()
