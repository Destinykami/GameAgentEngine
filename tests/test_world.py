"""世界层测试 (无网络, 阶段 0 骨架): 区域、实体、移动、时钟、距离、持久化往返。"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from persona_agent.world import World, Location, Entity, Player, distance


def _inazuma_locations() -> list[Location]:
    """稻妻城 5 区域 (阶段 0 骨架, NPC 尚未接入)。"""
    return [Location("主城街道", 0, 0),
            Location("治疗堂", 1, 0),
            Location("锻造坊", 2, 0),
            Location("眼狩署", 0, 1),
            Location("神樱庭", 0, 3)]


def _world(tmp_path, persistent: bool = True) -> World:
    path = os.path.join(str(tmp_path), "world.db") if persistent else None
    return World("稻妻城", _inazuma_locations(), path=path)


def test_move_and_clock(tmp_path):
    w = _world(tmp_path)
    w.add_entity(Player("旅行者", w.locations["主城街道"]))
    w.move("旅行者", "治疗堂", now=10.0)
    assert w.get("旅行者").location.name == "治疗堂"
    assert w.clock == 10.0
    w.close()


def test_clock_monotonic(tmp_path):
    """时钟取 max, 乱序事件不回退。"""
    w = _world(tmp_path)
    w.advance(20.0)
    w.advance(5.0)          # 乱序的更早事件
    assert w.clock == 20.0
    w.close()


def test_distance(tmp_path):
    w = _world(tmp_path)
    a = Player("旅行者", w.locations["主城街道"])
    b = Entity("npc", "桃音", w.locations["神樱庭"])
    c = Entity("npc", "刚郎", w.locations["主城街道"])
    assert distance(a, b) == pytest.approx(3.0)   # (0,0)→(0,3)
    assert distance(a, c) == pytest.approx(0.0)   # 同区域
    w.close()


def test_save_load_roundtrip(tmp_path):
    """保存/加载往返: 实体位置 + 时钟恢复一致。"""
    w = _world(tmp_path)
    w.add_entity(Player("旅行者", w.locations["主城街道"]))
    w.add_entity(Entity("npc", "桃音", w.locations["治疗堂"]))
    w.move("旅行者", "锻造坊", now=15.0)
    w.save()
    w.close()

    w2 = _world(tmp_path)          # 同 path, 重新打开
    w2.load()
    assert w2.get("旅行者").location.name == "锻造坊"
    assert w2.get("桃音").location.name == "治疗堂"
    assert w2.clock == pytest.approx(15.0)
    w2.close()


def test_inmemory_cannot_persist(tmp_path):
    w = _world(tmp_path, persistent=False)
    with pytest.raises(RuntimeError):
        w.save()
