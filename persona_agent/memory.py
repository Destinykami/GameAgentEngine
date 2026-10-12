"""记忆流: SQLite 存储 + 三维检索评分。

数据模型 (每条记忆):
- type:        observation | reflection | plan
- content:     自然语言内容
- timestamp:   游戏内时间 (小时, 单调递增)
- importance:  1-10, 记忆创建时打分 (以玩家为参照系时更高)
- player_id:   关联玩家; None = 世界记忆 / 自我记忆 (共享)
- evidence:    反思的证据记忆 id 列表 (JSON)
- confidence:  反思置信度 0-1
- valid:       反思是否仍有效 (冲突时失效)
- last_accessed: 上次被检索的时间 (用于 recency)

检索评分 (论文方法, 权重均为 1):
score(m, q) = recency(m) + importance(m) + relevance(m, q)
其中 recency = 0.995 ** Δt (Δt 为距上次被检索的游戏内小时数),
三者各自 Min-Max 归一化后相加。
"""

from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import dataclass, field, asdict
from typing import Any, Iterable, Sequence

from .embeddings import Embedder, cosine_similarity

RECENCY_DECAY = 0.995
ALPHA_RECENCY = 1.0
ALPHA_IMPORTANCE = 1.0
ALPHA_RELEVANCE = 1.0


@dataclass
class MemoryRecord:
    content: str
    timestamp: float
    importance: float = 5.0
    type: str = "observation"          # observation | reflection | plan
    player_id: str | None = None
    evidence: list[int] = field(default_factory=list)
    confidence: float = 1.0
    valid: bool = True
    last_accessed: float | None = None
    id: int | None = None              # 由数据库分配


class MemoryStore:
    """单个 NPC 的记忆存储 (自我 + 世界 + 各玩家关系流, 同库不同 player_id)。"""

    def __init__(self, embedder: Embedder, path: str = ":memory:") -> None:
        self._embedder = embedder
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._lock = threading.Lock()
        self._init_schema()
        # 缓存每条记忆的向量, 避免重复编码
        self._vec_cache: dict[int, list[float]] = {}

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
                    last_accessed REAL
                )
                """
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

    # ------------------------------------------------------------------ 写入
    def add(self, rec: MemoryRecord) -> int:
        """写入一条记忆, 返回分配的 id。"""
        with self._lock, self._conn:
            cur = self._conn.execute(
                """
                INSERT INTO memory
                    (type, content, timestamp, importance, player_id,
                     evidence, confidence, valid, last_accessed)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                ),
            )
            new_id = int(cur.lastrowid)
            # 立即编码缓存
            vec = self._embedder.embed([rec.content])[0]
            self._vec_cache[new_id] = vec
            return new_id

    # ------------------------------------------------------------------ 读取
    def _vec(self, rec: MemoryRecord) -> list[float]:
        if rec.id is not None and rec.id in self._vec_cache:
            return self._vec_cache[rec.id]
        vec = self._embedder.embed([rec.content])[0]
        if rec.id is not None:
            self._vec_cache[rec.id] = vec
        return vec

    def all_valid(self, player_id: str | None = None,
                  types: Sequence[str] | None = None) -> list[MemoryRecord]:
        """取全部有效记忆 (可按玩家/类型过滤), 用于反思与展示。"""
        sql = "SELECT * FROM memory WHERE valid = 1"
        args: list = []
        if player_id is not None:
            sql += " AND player_id = ?"
            args.append(player_id)
        if types:
            placeholders = ",".join("?" for _ in types)
            sql += f" AND type IN ({placeholders})"
            args.extend(types)
        with self._lock:
            rows = self._conn.execute(sql, args).fetchall()
        return [self._row_to_rec(r) for r in rows]

    def _row_to_rec(self, row: tuple) -> MemoryRecord:
        return MemoryRecord(
            id=row[0], type=row[1], content=row[2], timestamp=row[3],
            importance=row[4], player_id=row[5], evidence=json.loads(row[6]),
            confidence=row[7], valid=bool(row[8]), last_accessed=row[9],
        )

    # ------------------------------------------------------------------ 检索
    def retrieve(self, query: str, now: float,
                 player_id: str | None = None,
                 top_k: int = 8,
                 include_player: str | None = None,
                 min_score: float = 0.0) -> list[dict]:
        """三维检索。

        - query: 查询文本 (应已含玩家身份, 使 relevance 偏向该玩家)。
        - now: 当前游戏内时间。
        - player_id: 限定只检索某玩家的关系流 (可选)。
        - include_player: 在评分上额外给"属于该玩家"的记忆加权 (千人千面)。
        """
        q_vec = self._embedder.embed([query])[0]
        cands = self.all_valid(player_id=player_id)
        if not cands:
            return []

        # 计算原始分数
        raw = []
        recs = [c.last_accessed if c.last_accessed is not None else c.timestamp
                for c in cands]
        deltas = [max(0.0, now - t) for t in recs]
        recency = [RECENCY_DECAY ** d for d in deltas]
        importance = [c.importance / 10.0 for c in cands]
        relevance = [cosine_similarity(self._vec(c), q_vec) for c in cands]

        # Min-Max 归一化
        def norm(vals: list[float]) -> list[float]:
            lo, hi = min(vals), max(vals)
            if hi - lo < 1e-9:
                return [1.0 for _ in vals]
            return [(v - lo) / (hi - lo) for v in vals]

        r_norm, i_norm, s_norm = norm(recency), norm(importance), norm(relevance)
        for c, r, i, s in zip(cands, r_norm, i_norm, s_norm):
            score = (ALPHA_RECENCY * r + ALPHA_IMPORTANCE * i +
                     ALPHA_RELEVANCE * s)
            # 千人千面: 属于当前玩家的记忆获得额外加权
            if include_player and c.player_id == include_player:
                score += 0.5
            raw.append((score, c))

        raw.sort(key=lambda x: x[0], reverse=True)
        results = []
        for score, c in raw[:top_k]:
            if score < min_score:
                continue
            # 更新 last_accessed (recency 的语义: 距上次检索的时间)
            self._mark_accessed(c.id, now)
            results.append({
                "id": c.id,
                "type": c.type,
                "content": c.content,
                "timestamp": c.timestamp,
                "importance": c.importance,
                "player_id": c.player_id,
                "confidence": c.confidence,
                "evidence": c.evidence,
                "score": score,
            })
        return results

    def _mark_accessed(self, mem_id: int, now: float) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE memory SET last_accessed = ? WHERE id = ?",
                (now, mem_id),
            )

    # ------------------------------------------------------- 反思失效/更新
    def invalidate(self, mem_id: int, reason: str = "") -> None:
        """把某条反思标记为失效 (冲突时)。"""
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE memory SET valid = 0 WHERE id = ?", (mem_id,)
            )
        self._vec_cache.pop(mem_id, None)

    def update_confidence(self, mem_id: int, confidence: float) -> None:
        """更新反思置信度 (证据冲突时衰减)。"""
        confidence = max(0.0, min(1.0, confidence))
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE memory SET confidence = ? WHERE id = ?",
                (confidence, mem_id),
            )

    def count(self, player_id: str | None = None) -> int:
        sql = "SELECT COUNT(*) FROM memory WHERE valid = 1"
        args: list = []
        if player_id is not None:
            sql += " AND player_id = ?"
            args.append(player_id)
        with self._lock:
            return int(self._conn.execute(sql, args).fetchone()[0])

    # ------------------------------------------------------------------ 元数据
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

    def close(self) -> None:
        with self._lock:
            self._conn.close()
