"""world.py: 游戏世界层 —— 空间、实体、距离、世界状态持久化。

阶段 0 (世界骨架): 提供 Location / Entity / Player / World, 游戏时钟, 位置,
距离度量, 以及 World.save/load。世界状态单独存 world.db (实体位置 + 时钟),
与每个 NPC 的独立 db 分离, 不破坏"一 NPC 一库"约定。

阶段 0 不含感知 / 档位调度 / NPC 认知 —— 那些由后续阶段接入 (见 WorldPlan.md):
  阶段 1 多 NPC 注册, 阶段 2 空间感知, 阶段 3 距离调度, 阶段 4 世界事件,
  阶段 5 模拟驱动, 阶段 6 稻妻城·眼狩令 demo。
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from dataclasses import dataclass


# --------------------------------------------------------------------- 区域
@dataclass(frozen=True)
class Location:
    """有坐标的空间 (稻妻城: 主城街道 / 治疗堂 / 锻造坊 / 眼狩署 / 神樱庭)。"""
    name: str
    x: float = 0.0
    y: float = 0.0


# --------------------------------------------------------------------- 实体
@dataclass
class Entity:
    """世界实体: NPC 或玩家, 都有位置。kind = "npc" | "player"。"""
    kind: str
    name: str
    location: Location

    def move(self, location: Location) -> None:
        self.location = location


class Player(Entity):
    """玩家实体 (kind=player)。阶段 0 只是位置占位; 脚本驱动走位+台词在阶段 6。"""
    def __init__(self, name: str, location: Location) -> None:
        super().__init__(kind="player", name=name, location=location)


# --------------------------------------------------------------------- 距离
def distance(a: Entity, b: Entity) -> float:
    """两个实体间的欧氏距离 (同位置 = 0)。档位调度 (阶段 3) 以此为准。"""
    return ((a.location.x - b.location.x) ** 2 +
            (a.location.y - b.location.y) ** 2) ** 0.5


# --------------------------------------------------------------------- 世界
class World:
    """游戏世界: 持有区域、实体注册表、游戏时钟。

    世界状态单独持久化在 world.db (实体位置 + 时钟), 与每个 NPC 的独立 db 分离。
    不传 path 则为内存世界 (不可持久化, 供离线骨架测试)。
    """

    def __init__(self, name: str, locations: list[Location],
                 path: str | None = None,
                 perception_radius: float = 1.5) -> None:
        self.name = name
        self.locations: dict[str, Location] = {loc.name: loc for loc in locations}
        self.entities: dict[str, Entity] = {}
        self._npcs: dict[str, "NPC"] = {}   # NPC 认知对象 (实体注册表的子集)
        self.clock: float = 0.0            # 游戏内时间 (小时, 单调递增)
        self.perception_radius = perception_radius   # 视距: 玩家距 NPC 超过则感知不到
        self.path = path
        self._conn: sqlite3.Connection | None = None
        self._lock = threading.RLock()
        if path is not None:
            self._open(path)

    # ------------------------------------------------------------- 实体注册
    def add_entity(self, entity: Entity) -> None:
        self.entities[entity.name] = entity

    def get(self, name: str) -> Entity | None:
        return self.entities.get(name)

    def add_npc(self, name: str, persona_traits: dict[str, float], llm,
                embedder=None, data_dir: str = "data",
                location: str | None = None) -> "NPC":
        """创建或加载一个持久化 NPC (复用 NPC.create, 一 NPC 一库) 并登记入世界。

        location 缺省时放到第一个区域。NPC 认知对象与位置实体分开持有:
        _npcs 管认知, entities 管位置 (感知/档位调度用)。
        """
        from .npc import NPC   # 函数级导入, 避免模块加载期循环依赖
        npc = NPC.create(name, persona_traits, llm=llm, embedder=embedder,
                         data_dir=data_dir)
        self._npcs[name] = npc
        loc = self.locations[location] if location else next(iter(self.locations.values()))
        self.add_entity(Entity("npc", name, loc))
        return npc

    def add_player(self, name: str, location: str) -> Player:
        """登记一个玩家实体到某区域。"""
        player = Player(name, self.locations[location])
        self.add_entity(player)
        return player

    def npc(self, name: str) -> "NPC | None":
        return self._npcs.get(name)

    # ------------------------------------------------------------- 空间感知
    def perceive(self, npc_name: str, now: float,
                 radius: float | None = None) -> list[int]:
        """空间感知: NPC 感知视距内的玩家, 生成自然语言观察喂 npc.observe()。

        替代手写 observe(): 玩家走进 NPC 视距 → NPC 自然"看到"并记下。
        粒度随认知档位: full=富细节 (玩家+位置+与NPC的接近), compressed=稀疏
        (仅在场), idle=不感知。视距外 (distance > radius) 感知不到。
        重复感知同一在场走既有观察去重 (0.92 合并), 不灌水。返回观察 id 列表。
        """
        npc = self._npcs.get(npc_name)
        if npc is None or npc._tier == "idle":
            return []
        me = self.entities[npc_name]
        r = self.perception_radius if radius is None else radius
        ids: list[int] = []
        for ent in self.entities.values():
            if ent.kind != "player" or distance(me, ent) > r:
                continue   # 非玩家或视距外
            if npc._tier == "full":
                content = f"{ent.name} 出现在 {me.location.name}, 靠近 {npc_name}"
            else:   # compressed
                content = f"{ent.name} 在 {me.location.name}"
            ids.append(npc.observe(content, now, player_id=ent.name))
        return ids

    # ------------------------------------------------------------- 移动与时钟
    def move(self, name: str, location_name: str, now: float) -> None:
        """把实体移到某区域, 并推进时钟。"""
        self.entities[name].move(self.locations[location_name])
        self.advance(now)

    def advance(self, now: float) -> None:
        """推进游戏时钟 (取 max, 容忍乱序事件)。"""
        if now > self.clock:
            self.clock = now

    # ------------------------------------------------------------- 持久化
    def _open(self, path: str) -> None:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS entity "
            "(name TEXT PRIMARY KEY, kind TEXT, location TEXT, x REAL, y REAL)")
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)")

    def save(self) -> None:
        """把世界状态 (实体位置 + 时钟) 写入 world.db。"""
        if self._conn is None:
            raise RuntimeError("该世界是内存世界, 无法持久化 (构造时请传 path)")
        with self._lock, self._conn:
            self._conn.execute("DELETE FROM entity")
            for ent in self.entities.values():
                self._conn.execute(
                    "INSERT INTO entity (name, kind, location, x, y) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (ent.name, ent.kind, ent.location.name,
                     ent.location.x, ent.location.y))
            self._conn.execute(
                "INSERT OR REPLACE INTO meta (key, value) VALUES ('clock', ?)",
                (json.dumps(self.clock),))

    def load(self) -> None:
        """从 world.db 恢复世界状态 (实体位置 + 时钟)。"""
        if self._conn is None:
            raise RuntimeError("该世界是内存世界, 无法加载")
        with self._lock:
            for name, kind, loc_name, x, y in self._conn.execute(
                    "SELECT name, kind, location, x, y FROM entity"):
                loc = self.locations.get(loc_name)
                if loc is None:   # 区域表漂移兜底: 按存下的坐标重建
                    loc = Location(loc_name, x, y)
                    self.locations[loc_name] = loc
                self.entities[name] = Entity(kind, name, loc)
            row = self._conn.execute(
                "SELECT value FROM meta WHERE key='clock'").fetchone()
            if row:
                self.clock = float(json.loads(row[0]))

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None
