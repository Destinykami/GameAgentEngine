"""单 NPC 记忆仓储：独占 SQLite 连接、迁移、查询和提交。"""

from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Iterable, Iterator, Sequence
from contextlib import contextmanager
from typing import Any

from .models import MemoryRecord


class MemoryRepository:
    def __init__(self, path: str) -> None:
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._lock = threading.Lock()
        self._init_schema()

    def _init_schema(self) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS memory (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    type TEXT NOT NULL,
                    content TEXT NOT NULL,
                    timestamp REAL NOT NULL,
                    importance REAL NOT NULL DEFAULT 5.0,
                    player_id TEXT,
                    evidence TEXT DEFAULT '[]',
                    confidence REAL DEFAULT 1.0,
                    valid INTEGER DEFAULT 1,
                    last_accessed REAL,
                    base_confidence REAL DEFAULT 1.0,
                    base_importance REAL,
                    hearsay INTEGER DEFAULT 0,
                    hop INTEGER DEFAULT 0,
                    consolidated INTEGER DEFAULT 0,
                    last_reinforced REAL
                )
                """
            )
            # 旧库迁移: H1 之前建的库没有 base_confidence 列, 补齐 (缺省 1.0,
            # 旧反思的首次衰减以 1.0 为基准, 比真实初始值略高, 一次性小漂移可接受)
            cols = {r[1] for r in self._conn.execute("PRAGMA table_info(memory)")}
            if "base_confidence" not in cols:
                self._conn.execute(
                    "ALTER TABLE memory ADD COLUMN base_confidence REAL DEFAULT 1.0"
                )
            # 旧库迁移 (E1): base_importance 是衰减基线, 必须逐行 = 当前 importance
            # (不能用常量缺省 —— 各行 importance 不同)。旧行从当前值起继续衰减,
            # 一次性重置基线, 可接受。
            if "base_importance" not in cols:
                self._conn.execute(
                    "ALTER TABLE memory ADD COLUMN base_importance REAL"
                )
                self._conn.execute(
                    "UPDATE memory SET base_importance = importance "
                    "WHERE base_importance IS NULL"
                )
            # 旧库迁移 (S4): hearsay/hop 是传闻链状态, 旧行全是亲见 (0/0)
            if "hearsay" not in cols:
                self._conn.execute(
                    "ALTER TABLE memory ADD COLUMN hearsay INTEGER DEFAULT 0"
                )
            if "hop" not in cols:
                self._conn.execute(
                    "ALTER TABLE memory ADD COLUMN hop INTEGER DEFAULT 0"
                )
            # 旧库迁移 (M1): consolidated 是固化标记, 旧行全部未固化 (0)
            if "consolidated" not in cols:
                self._conn.execute(
                    "ALTER TABLE memory ADD COLUMN consolidated INTEGER DEFAULT 0"
                )
            # 旧库迁移 (F2-1): 强化限速时间锚点。旧行从 last_accessed/timestamp
            # 起算, 避免升级后第一次 merge 立刻 +1。
            if "last_reinforced" not in cols:
                self._conn.execute(
                    "ALTER TABLE memory ADD COLUMN last_reinforced REAL"
                )
                self._conn.execute(
                    "UPDATE memory SET last_reinforced = "
                    "COALESCE(last_accessed, timestamp) "
                    "WHERE last_reinforced IS NULL"
                )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_player ON memory(player_id)"
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_type ON memory(type)"
            )
            # NPC 元数据 (名称/人格/游戏时钟): 与记忆流同库, 一个 NPC 一个 .db
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
            )
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS memory_source ("
                "source_id TEXT PRIMARY KEY, memory_id INTEGER NOT NULL)"
            )
            self._conn.execute("CREATE INDEX IF NOT EXISTS source_memory ON memory_source(memory_id)")
            self._conn.execute("CREATE INDEX IF NOT EXISTS memory_stream_time ON memory(player_id,timestamp,id)")


    @contextmanager
    def insert(self, rec: MemoryRecord, source_id: str | None = None) -> Iterator[int]:
        """写入并提供分配的 id；上下文成功退出才提交。"""
        # 衰减基线: 未显式设定时回退到 importance (E1) —— 只设 importance 的
        # 调用方 (observe/_save_plan/_save_obs/测试) 自动把基线设为初始重要性。
        base_imp = (rec.base_importance if rec.base_importance is not None
                    else rec.importance)
        last_reinforced = (rec.last_reinforced if rec.last_reinforced is not None
                           else rec.timestamp)
        with self._lock, self._conn:
            cur = self._conn.execute(
                """
                INSERT INTO memory
                    (type, content, timestamp, importance, player_id,
                     evidence, confidence, valid, last_accessed,
                     base_confidence, base_importance, hearsay, hop,
                     consolidated, last_reinforced)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    rec.type,
                    rec.content,
                    rec.timestamp,
                    rec.importance,
                    rec.player_id,
                    json.dumps(rec.evidence),
                    rec.confidence,
                    1 if rec.valid else 0,
                    rec.last_accessed,
                    rec.base_confidence,
                    base_imp,
                    1 if rec.hearsay else 0,
                    rec.hop,
                    1 if rec.consolidated else 0,
                    last_reinforced,
                ),
            )
            new_id = int(cur.lastrowid)
            if source_id is not None:
                self._conn.execute("INSERT INTO memory_source VALUES (?,?)", (source_id, new_id))
            yield new_id

    def projected_id(self, source_id: str) -> int | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT memory_id FROM memory_source WHERE source_id=?", (source_id,)).fetchone()
        return row[0] if row else None

    def sources(self, memory_id: int) -> list[str]:
        with self._lock:
            return [row[0] for row in self._conn.execute(
                "SELECT source_id FROM memory_source WHERE memory_id=? ORDER BY rowid", (memory_id,))]

    def link_source(self, source_id: str, memory_id: int) -> None:
        with self._lock, self._conn:
            self._conn.execute("INSERT INTO memory_source VALUES (?,?)", (source_id, memory_id))

    def unlinked(self, limit: int = 100) -> list[MemoryRecord]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT m.* FROM memory m WHERE NOT EXISTS "
                "(SELECT 1 FROM memory_source s WHERE s.memory_id=m.id) ORDER BY m.id LIMIT ?",
                (limit,)).fetchall()
        return [self._row_to_rec(row) for row in rows]

    def context_candidates(self, player_id: str, now: float, *, limit: int = 8,
                           since: float | None = None, important: bool = False,
                           summaries: bool = False) -> list[MemoryRecord]:
        sql = "SELECT * FROM memory WHERE valid=1 AND (player_id=? OR player_id IS NULL) AND timestamp<=?"
        args: list = [player_id, now]
        if since is not None:
            sql += " AND timestamp>=?"
            args.append(since)
        if important:
            sql += " AND (importance>=6 OR type IN ('reflection','episode','identity'))"
        if summaries:
            sql += " AND type IN ('reflection','episode','identity')"
        sql += " ORDER BY timestamp DESC,id DESC LIMIT ?"
        args.append(max(0, min(limit, 512)))
        with self._lock:
            rows = self._conn.execute(sql, args).fetchall()
        return [self._row_to_rec(row) for row in rows]

    def recent_observations(self, player_id: str | None, limit: int) -> list[MemoryRecord]:
        scope = 'player_id IS NULL' if player_id is None else 'player_id=?'
        args = [] if player_id is None else [player_id]
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM memory WHERE valid=1 AND type='observation' AND " + scope +
                " ORDER BY id DESC LIMIT ?", [*args, max(0, limit)]).fetchall()
        return [self._row_to_rec(row) for row in reversed(rows)]

    def all_valid(self, player_id: str | None = None,
                  types: Sequence[str] | None = None,
                  shared: bool = False,
                  consolidated: bool | None = None,
                  include_shared: bool = False,
                  hearsay_only: bool = False) -> list[MemoryRecord]:
        """取全部有效记忆 (可按玩家/类型过滤), 用于反思与展示。

        E2 语义拆分: `player_id=None` 是"不过滤" (返回所有玩家+共享流, 供衰减/
        计划查询/近期上下文); `shared=True` 是"只取共享流" (player_id IS NULL,
        世界/自我记忆)。二者不再混用 —— 自我反思要的是共享流 (我是谁), 不是
        全玩家关系观察 (谁对我做了什么), 旧实现用 None 拿全玩家流, 自我反思被
        关系观察污染 (E8)。

        E5: `ORDER BY id` —— id 自增即插入序 (= 时间序)。多处用 `[-n:]` 取"最近
        n 条" (find_similar_observation 去重窗口、反思近期观察、世界记忆上下文),
        旧实现无 ORDER BY, 靠 SQLite 恰好按 rowid 返回, 是隐性依赖, 加显式排序。

        include_shared: 与 player_id 联用, 返回该玩家面 + 共享流 (player_id IS
        NULL)。对话检索用它隔离其他玩家的私有记忆; 默认 False 保持旧语义
        (只取该玩家面)。
        """
        sql = "SELECT * FROM memory WHERE valid = 1"
        args: list = []
        if shared:
            sql += " AND player_id IS NULL"
        elif player_id is not None:
            if include_shared:
                sql += " AND (player_id = ? OR player_id IS NULL)"
            else:
                sql += " AND player_id = ?"
            args.append(player_id)
        if types:
            placeholders = ",".join("?" for _ in types)
            sql += f" AND type IN ({placeholders})"
            args.extend(types)
        if consolidated is not None:   # M1: None=不过滤(现行为), True/False 按固化标记筛
            sql += " AND consolidated = ?"
            args.append(1 if consolidated else 0)
        if hearsay_only:
            sql += " AND hearsay = 1"   # F4-1: 只看传闻记忆 (转述候选)
        sql += " ORDER BY id"
        with self._lock:
            rows = self._conn.execute(sql, args).fetchall()
        return [self._row_to_rec(r) for r in rows]


    def _row_to_rec(self, row: tuple) -> MemoryRecord:
        return MemoryRecord(
            id=row[0], type=row[1], content=row[2], timestamp=row[3],
            importance=row[4], player_id=row[5], evidence=json.loads(row[6]),
            confidence=row[7], valid=bool(row[8]), last_accessed=row[9],
            base_confidence=row[10], base_importance=row[11],
            hearsay=bool(row[12]), hop=row[13], consolidated=bool(row[14]),
            last_reinforced=row[15] if len(row) > 15 else None,
        )


    def mark_accessed(self, mem_id: int, now: float) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE memory SET last_accessed = ? WHERE id = ?",
                (now, mem_id),
            )


    def invalidate(self, mem_id: int, reason: str = "") -> None:
        """把某条反思标记为失效 (冲突时)。"""
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE memory SET valid = 0 WHERE id = ?", (mem_id,)
            )


    def update_confidence(self, mem_id: int, confidence: float) -> None:
        """更新反思置信度 (证据冲突时衰减)。"""
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE memory SET confidence = ? WHERE id = ?",
                (confidence, mem_id),
            )


    def set_importance(self, mem_id: int, importance: float) -> None:
        """写入已由策略 / 门面确定的重要性值。"""
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE memory SET importance = ? WHERE id = ?",
                (importance, mem_id),
            )


    def count(self, player_id: str | None = None) -> int:
        sql = "SELECT COUNT(*) FROM memory WHERE valid = 1"
        args: list = []
        if player_id is not None:
            sql += " AND player_id = ?"
            args.append(player_id)
        with self._lock:
            return int(self._conn.execute(sql, args).fetchone()[0])


    def mark_consolidated(self, mem_ids: Iterable[int]) -> int:
        """M1 固化标记: 把被情节摘要 (episode) 吸收的原始观察标 consolidated=1。
        记忆仍 valid、仍可检索, 只是退出冲突扫描 (由 episode 顶替"更晚证据"角色)。
        返回标记的条数。"""
        ids = [i for i in mem_ids if i is not None]
        if not ids:
            return 0
        q = ",".join("?" for _ in ids)
        with self._lock, self._conn:
            cur = self._conn.execute(
                f"UPDATE memory SET consolidated = 1 WHERE id IN ({q}) AND consolidated = 0",
                ids)
            return cur.rowcount


    def all_invalid(self) -> list[MemoryRecord]:
        """取全部已失效记忆 (冲突失效), 按时间排序, 供审查。

        注意: 遗忘改为降权后不再产生失效记录, 这里只剩冲突失效的反思。
        F6-9: 复用 _row_to_rec 读全列, 新加字段 (hearsay/hop/consolidated/
        last_reinforced) 不再被截断或默认化。
        """
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM memory WHERE valid = 0 ORDER BY timestamp, id"
            ).fetchall()
        return [self._row_to_rec(r) for r in rows]


    def set_meta(self, key: str, value: Any) -> None:
        """存一条 NPC 元数据 (JSON 序列化)。"""
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
                (key, json.dumps(value)),
            )


    def get_meta(self, key: str, default: Any = None) -> Any:
        """取一条 NPC 元数据; 不存在返回 default。"""
        with self._lock:
            row = self._conn.execute(
                "SELECT value FROM meta WHERE key = ?", (key,)
            ).fetchone()
        return json.loads(row[0]) if row else default


    def db_path(self) -> str | None:
        """文件库的绝对路径; :memory: 返回 None。"""
        row = self._conn.execute("PRAGMA database_list").fetchone()
        return row[2] if row and row[2] not in (":memory:", None, "") else None


    def is_persistent(self) -> bool:
        """是否为文件库 (可持久化); :memory: 返回 False。"""
        return self.db_path() is not None


    def backup(self, path: str) -> None:
        """锁内用 SQLite backup 导出已提交快照，不复制 WAL 临时文件。"""
        with self._lock:
            target = sqlite3.connect(path)
            try:
                self._conn.backup(target)
            finally:
                target.close()

    def close(self) -> None:
        with self._lock:
            self._conn.close()


    @contextmanager
    def edit_observation(self, mem_id: int, source_id: str | None = None) -> Iterator[MemoryRecord]:
        """锁内读取可编辑快照；调用方成功退出后才提交其维护字段。"""
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM memory WHERE id = ?", (mem_id,)).fetchone()
            if row is None:
                raise ValueError(f"观察 {mem_id} 不存在")
            rec = self._row_to_rec(row)
            yield rec
            with self._conn:
                self._conn.execute(
                    "UPDATE memory SET last_accessed = ?, importance = ?, "
                    "base_importance = ?, last_reinforced = ?, "
                    "hearsay = ?, hop = ?, content = ? WHERE id = ?",
                    (rec.last_accessed, rec.importance, rec.base_importance,
                     rec.last_reinforced, int(rec.hearsay), rec.hop, rec.content, mem_id))
                if source_id is not None:
                    self._conn.execute("INSERT INTO memory_source VALUES (?,?)", (source_id, mem_id))
