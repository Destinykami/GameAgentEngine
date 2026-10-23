"""世界快照的 SQLite 存储；不依赖世界运行或 NPC 认知。"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from collections.abc import Iterable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

from .entities import Entity, Location


@dataclass
class WorldSnapshot:
    entities: list[Entity]
    metadata: dict[str, Any]


class WorldStore:
    """持有世界库连接与锁，以快照上下文暴露读写边界。"""

    def __init__(self, path: str) -> None:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._lock = threading.RLock()
        self._init_schema()

    def _init_schema(self) -> None:
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS entity ("
            "name TEXT PRIMARY KEY, kind TEXT, location TEXT, x REAL, y REAL,"
            " health INTEGER DEFAULT 100, attack INTEGER DEFAULT 10,"
            " defense INTEGER DEFAULT 0, goal TEXT DEFAULT '',"
            " dead INTEGER DEFAULT 0, role TEXT DEFAULT '',"
            " history TEXT DEFAULT '[]', reasons TEXT DEFAULT '[]')")
        # 保留旧五列实体表的逐列迁移及其缺省值。
        cols = {r[1] for r in self._conn.execute("PRAGMA table_info(entity)")}
        for col, ddl in (
                ("health", "INTEGER DEFAULT 100"),
                ("attack", "INTEGER DEFAULT 10"),
                ("defense", "INTEGER DEFAULT 0"),
                ("goal", "TEXT DEFAULT ''"),
                ("dead", "INTEGER DEFAULT 0"),
                ("role", "TEXT DEFAULT ''"),
                ("history", "TEXT DEFAULT '[]'"),
                ("reasons", "TEXT DEFAULT '[]'")):
            if col not in cols:
                self._conn.execute(f"ALTER TABLE entity ADD COLUMN {col} {ddl}")
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)")

    @contextmanager
    def write_snapshot(self, entities: Iterable[Entity],
                       metadata: Mapping[str, Any]) -> Iterator[None]:
        """替换快照；上下文退出才提交，异常时回滚世界库。"""
        with self._lock, self._conn:
            self._conn.execute("DELETE FROM entity")
            for ent in entities:
                self._conn.execute(
                    "INSERT INTO entity (name, kind, location, x, y,"
                    " health, attack, defense, goal, dead, role, history,"
                    " reasons) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (ent.name, ent.kind, ent.location.name,
                     ent.location.x, ent.location.y,
                     ent.health, ent.attack, ent.defense, ent.goal,
                     1 if ent.dead else 0, ent.role,
                     json.dumps(ent.history), json.dumps(ent.reasons)))
            for key, value in metadata.items():
                self._conn.execute(
                    "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
                    (key, json.dumps(value)))
            yield

    @contextmanager
    def read_snapshot(self) -> Iterator[WorldSnapshot]:
        """读取快照；调用方完成恢复前保持锁，不调用任何认知组件。"""
        with self._lock:
            entities = []
            for row in self._conn.execute(
                    "SELECT name, kind, location, x, y, health, attack, defense,"
                    " goal, dead, role, history, reasons FROM entity"):
                (name, kind, loc_name, x, y, health, attack, defense,
                 goal, dead, role, history, reasons) = row
                entities.append(Entity(
                    kind=kind, name=name, location=Location(loc_name, x, y),
                    health=health if health is not None else 100,
                    attack=attack if attack is not None else 10,
                    defense=defense if defense is not None else 0,
                    goal=goal or "", dead=bool(dead), role=role or "",
                    history=json.loads(history) if history else [],
                    reasons=json.loads(reasons) if reasons else []))
            metadata = {key: json.loads(value) for key, value in
                        self._conn.execute("SELECT key, value FROM meta")}
            yield WorldSnapshot(entities, metadata)

    def close(self) -> None:
        self._conn.close()
