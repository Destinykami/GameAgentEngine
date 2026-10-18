"""玩家感知过渡驱动开关回归 (F6-11, 缺省关)。"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from persona_agent import Location, World
from tests.test_persistence import _StubLLM, TRAITS


def test_transition_perception_skips_repeated_presence(tmp_path):
    w = World("w", [Location("甲", 0, 0), Location("乙", 1, 0)],
              player_perception_transition=True)
    w.add_npc("A", dict(TRAITS), llm=_StubLLM(),
              data_dir=str(tmp_path / "A"), location="甲")
    p = w.add_player("P", "甲")
    w.schedule_tiers(1.0)
    first = w.perceive("A", 1.0)
    second = w.perceive("A", 2.0)   # 同一位置/档位 → 跳过
    assert first and second == []
    # 换区域 → 重新观察
    p.move(w.locations["乙"])
    w.schedule_tiers(3.0)
    third = w.perceive("A", 3.0)
    assert third
    # 离开视距再回来 → 重新观察
    p.move(w.locations["甲"])
    w.schedule_tiers(4.0)
    w.perceive("A", 4.0)   # 这一条是回到甲后的新状态 (位置变化)
    assert w.npc("A").store.all_valid(player_id="P", types=["observation"])
    w.close()
