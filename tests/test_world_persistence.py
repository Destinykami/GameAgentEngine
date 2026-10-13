"""世界实体状态持久化测试 (M9 回归)。

save/load 往返恢复实体全量状态: 血/攻防/目标/死亡/角色/历史/理由 —— 跨进程
续跑后将军的血量、旅行者的攻与已积累的理由、角色的特殊判定都不丢, 自治弧线
不从一半重头再来。另测旧库 (M9 前只有 5 列) 迁移不崩、按默认值兜底。
无网络。
"""

from __future__ import annotations

import os
import sqlite3
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from persona_agent.world import World, Location, Entity


def _locs() -> list[Location]:
    return [Location("主城街道", 0, 0), Location("治疗堂", 1, 0),
            Location("锻造坊", 2, 0)]


def _world(tmp_path) -> World:
    return World("稻妻城", _locs(),
                 path=os.path.join(str(tmp_path), "world.db"))


def test_entity_full_state_roundtrip(tmp_path):
    """实体全量状态 save/load 往返不丢: 血/攻防/目标/角色/历史/理由。"""
    w = _world(tmp_path)
    w.add_entity(Entity(
        kind="player", name="旅行者", location=w.locations["锻造坊"],
        health=40, attack=24, defense=3, goal="推翻眼狩令",
        role="", history=["对 刚郎 说: 帮我锻一把刀", "被 雷电将军 盯上了"],
        reasons=["从小梅的孤本典籍中取证: 眼狩令令持眼者流离失所",
                 "听桃音讲述持眼者被迫离散之苦"]))
    w.add_entity(Entity(
        kind="npc", name="刚郎", location=w.locations["锻造坊"],
        health=80, attack=15, defense=2, role="blacksmith"))
    w.advance(37.5)
    w.save()
    w.close()

    w2 = _world(tmp_path)
    w2.load()
    t = w2.get("旅行者")
    assert t.location.name == "锻造坊"
    assert t.health == 40, "血量应恢复 (旧实现: 回 100)"
    assert t.attack == 24, "攻应恢复 (旧实现: 回 10)"
    assert t.defense == 3
    assert t.goal == "推翻眼狩令", "目标应恢复 (旧实现: 清空, 决策失去驱动力)"
    assert t.history == ["对 刚郎 说: 帮我锻一把刀", "被 雷电将军 盯上了"], \
        "自身历史应恢复 (非全知视图)"
    assert t.reasons == ["从小梅的孤本典籍中取证: 眼狩令令持眼者流离失所",
                         "听桃音讲述持眼者被迫离散之苦"], \
        "已积累的理由应恢复 (旧实现: 清零, 说服弧线作废)"
    g = w2.get("刚郎")
    assert g.role == "blacksmith", "角色应恢复 (旧实现: 清空, 锻刀特殊判定失效)"
    assert g.health == 80
    assert w2.clock == pytest.approx(37.5)
    w2.close()


def test_dead_entity_stays_dead(tmp_path):
    """阵亡实体往返后仍是阵亡 (不复活回 100 血)。"""
    w = _world(tmp_path)
    w.add_entity(Entity(kind="npc", name="小梅", location=w.locations["治疗堂"],
                        health=0, dead=True, role="scholar"))
    w.save()
    w.close()

    w2 = _world(tmp_path)
    w2.load()
    m = w2.get("小梅")
    assert m.dead is True, "死者不应复活"
    assert m.health == 0
    assert m.is_alive() is False
    w2.close()


def test_old_schema_migration(tmp_path):
    """M9 前的旧库 (entity 只有 5 列) 打开不崩, 实体按默认值兜底恢复。"""
    path = os.path.join(str(tmp_path), "old_world.db")
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE entity "
                 "(name TEXT PRIMARY KEY, kind TEXT, location TEXT, x REAL, y REAL)")
    conn.execute("INSERT INTO entity VALUES ('桃音', 'npc', '治疗堂', 1.0, 0.0)")
    conn.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")
    conn.execute("INSERT INTO meta VALUES ('clock', '12.0')")
    conn.commit()
    conn.close()

    w = World("稻妻城", _locs(), path=path)   # _open 触发迁移
    w.load()
    momone = w.get("桃音")
    assert momone is not None, "旧库实体应恢复"
    assert momone.location.name == "治疗堂"
    assert momone.health == 100, "旧库无血量, 按默认 100 兜底"
    assert momone.attack == 10
    assert momone.dead is False
    assert momone.history == [] and momone.reasons == []
    assert w.clock == pytest.approx(12.0)
    # 迁移后再次 save 不崩, 新列已就位
    w.save()
    w.close()
