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

# 观察层去重: 同玩家的近义观察 (>= 阈值) 合并而非重复入库。
# 观察比反思更公式化、近义重复更多, 阈值比反思去重 (0.95) 略松。
OBS_DEDUP_THRESHOLD = 0.92

# 遗忘 = 部分衰减降权 (不直接删除): importance *= 0.5 ** (age / half_life),
# 渐近降到 MIN_IMPORTANCE 为止, 记忆**保留**(valid 恒为 1), 只是 importance
# 被调低。检索的 importance 维用 importance/10, 所以老记忆自然跌出前排,
# 但仍在库里 —— 被回忆(last_accessed 刷新)或 merge 时又能升回来。
# - age: 距 max(timestamp, last_accessed) 的小时数 —— 被回忆过的记忆衰减更慢
# - 半衰期: 原始观察最先淡去, 反思(高阶认知)留存最久, 计划隔夜即过期
# - FORGET_FLOOR 是强度(0-1)下限; MIN_IMPORTANCE = FORGET_FLOOR*10 是
#   对应的 importance(0-10)下限 —— 降权到此为止, 不再删。
FORGET_FLOOR = 0.15
MIN_IMPORTANCE = FORGET_FLOOR * 10.0   # = 1.5, importance 降权下限
FORGET_HALF_LIVES: dict[str, float] = {
    "observation": 48.0,   # ~2 天: 没被固化、没被回忆的原始事件先降权
    "reflection": 168.0,   # ~2 周: 高阶认知降权最慢
    "plan": 24.0,          # ~1 天: 计划隔夜即降权
}


@dataclass
class MemoryRecord:
    content: str
    timestamp: float
    importance: float = 5.0
    type: str = "observation"          # observation | reflection | plan
    player_id: str | None = None
    evidence: list[int] = field(default_factory=list)
    confidence: float = 1.0            # 当前置信度 (反思会被冲突衰减)
    base_confidence: float = 1.0       # 创建时的初始置信度 (幂等衰减的重算基准)
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
        # 缓存每条记忆的向量, 避免重复编码。
        # L4: 此缓存是进程内、无上限、**不跨进程持久化**。HashEmbedder (确定性哈希,
        # 纯内存) 下冷启动无感; 但 RealEmbedder (网络) 下从磁盘恢复一个大世界后,
        # 首波检索要为每条记忆重新嵌入 (O(n) 次网络调用) —— 这是"向量不入库"的
        # 有意取舍: 持久化向量要每条存几百维浮点, 库膨胀且与嵌入模型版本耦合。
        # 量大 (上千记忆 + 频繁重启) 后再议持久化或 LRU 上限。
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
                    last_accessed REAL,
                    base_confidence REAL DEFAULT 1.0
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
                     evidence, confidence, valid, last_accessed,
                     base_confidence)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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

    def vector(self, rec: MemoryRecord) -> list[float]:
        """取某记忆的向量 (命中缓存则不重嵌入)。供反思去重等需比较既有记忆的
        向量场景使用 (L1): 已入库记忆的向量在 add 时已缓存, 此处零嵌入成本。"""
        return self._vec(rec)

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
            base_confidence=row[10],
        )

    # ------------------------------------------------------------------ 检索
    def retrieve(self, query: str, now: float,
                 player_id: str | None = None,
                 top_k: int = 8,
                 include_player: str | None = None,
                 min_score: float = 0.0,
                 types: Sequence[str] | None = None,
                 mark_accessed: bool = True,
                 min_relevance: float = 0.0) -> list[dict]:
        """三维检索。

        - query: 查询文本 (应已含玩家身份, 使 relevance 偏向该玩家)。
        - now: 当前游戏内时间。
        - player_id: 限定只检索某玩家的关系流 (可选)。
        - include_player: 在评分上额外给"属于该玩家"的记忆加权 (千人千面)。
        - types: 限定记忆类型 (如 ["observation"]), 用于让反思只以真实观察为证据,
          切断"反思引用反思"的级联。
        - mark_accessed: 是否把进 top_k 的记忆刷新 last_accessed (遗忘锚点)。
          对话 (NPC 真正拿记忆开口) 用默认 True —— 进 top_k 即"被回忆", 抗遗忘;
          反思证据检索传 False —— 候选证据只是"被考虑", 真正被引用的观察已由
          "被反思引用即保护"单独兜底, 不该把 top_k 里没被引用的也一并续命
          (M7: 反思 10×3 问静默给无关观察续命)。
        - min_relevance: 原始余弦相关性下限, 低于它的候选直接剔除 (归一化前)。
          min-max 归一化会把"小存储里最不差的那条"抬成满分, min_score=0.0 又
          全收, 于是小库必返回满 top_k 含无关记忆; 一个绝对相关性下限挡住这种
          灌水 (M7)。默认 0.0 不过滤, 行为与旧版一致。
        """
        q_vec = self._embedder.embed([query])[0]
        cands = self.all_valid(player_id=player_id, types=types)
        if not cands:
            return []

        # 计算原始分数
        recs = [c.last_accessed if c.last_accessed is not None else c.timestamp
                for c in cands]
        deltas = [max(0.0, now - t) for t in recs]
        recency = [RECENCY_DECAY ** d for d in deltas]
        importance = [c.importance / 10.0 for c in cands]
        relevance = [cosine_similarity(self._vec(c), q_vec) for c in cands]

        # 相关性下限 (M7): 归一化前按原始余弦剔除无关候选, 挡住 min-max 把
        # "小存储里最不差的那条"抬成满分塞进 top_k 的灌水。
        if min_relevance > 0.0:
            keep = [s >= min_relevance for s in relevance]
            cands = [c for c, k in zip(cands, keep) if k]
            recency = [r for r, k in zip(recency, keep) if k]
            importance = [i for i, k in zip(importance, keep) if k]
            relevance = [s for s, k in zip(relevance, keep) if k]
            if not cands:
                return []

        # Min-Max 归一化
        def norm(vals: list[float]) -> list[float]:
            lo, hi = min(vals), max(vals)
            if hi - lo < 1e-9:
                return [1.0 for _ in vals]
            return [(v - lo) / (hi - lo) for v in vals]

        r_norm, i_norm, s_norm = norm(recency), norm(importance), norm(relevance)
        raw = []
        for c, r, i, s in zip(cands, r_norm, i_norm, s_norm):
            score = (ALPHA_RECENCY * r + ALPHA_IMPORTANCE * i +
                     ALPHA_RELEVANCE * s)
            # 置信度折减 (H2): 被冲突衰减的反思按信念强度打折 —— check_conflicts
            # 的幂等衰减每多一条冲突证据就折半一次, 这里乘 confidence 与之一一对应,
            # 削弱的信念检索排名随之下降 (博客 2.2.5 "防不可靠推断被放大" 的落点)。
            # 观察/计划的 confidence 恒 1.0, 不受影响。
            score *= c.confidence
            # 千人千面: 属于当前玩家的记忆获得额外加权
            if include_player and c.player_id == include_player:
                score += 0.5
            raw.append((score, c))

        raw.sort(key=lambda x: x[0], reverse=True)
        results = []
        for score, c in raw[:top_k]:
            if score < min_score:
                continue
            # 更新 last_accessed (recency 的语义: 距上次检索的时间); 反思证据检索
            # 传 mark_accessed=False 关闭 —— 候选 ≠ 回忆 (M7)。
            if mark_accessed:
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

    def _set_importance(self, mem_id: int, importance: float) -> None:
        """设某条记忆的 importance (遗忘降权用; 只降不升, 下限 MIN_IMPORTANCE)。"""
        importance = max(MIN_IMPORTANCE, min(10.0, importance))
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

    # ------------------------------------------------------------------ 观察去重
    def find_similar_observation(self, content: str,
                                 player_id: str | None = None,
                                 threshold: float = OBS_DEDUP_THRESHOLD,
                                 recent_n: int = 50) -> MemoryRecord | None:
        """在同玩家的近期观察里找语义近义的一条 (>= threshold), 否则 None。

        只在观察层做 (反思去重在 reflection.py), 且限定同一玩家流 ——
        跨玩家"相似"是不同关系, 不该合并。
        """
        cands = self.all_valid(player_id=player_id,
                               types=["observation"])[-recent_n:]
        if not cands:
            return None
        v_new = self._embedder.embed([content])[0]
        best: MemoryRecord | None = None
        best_s = 0.0
        for c in cands:
            s = cosine_similarity(self._vec(c), v_new)
            if s >= threshold and s > best_s:
                best, best_s = c, s
        return best

    def merge_observation(self, mem_id: int, now: float) -> float:
        """合并重复观察: 刷新 last_accessed (重复发生 = 记忆强化, 抗遗忘),
        并以固定 +1 (上限 10) 提升 importance —— 反复发生的事件更突出。

        强化是**固定 +1 的重复计数**, 不加新观察的完整 importance: 事件的重要
        性在首次入库时已计入, 重复合并再加一次全量等于双重计分 (一条重要性 9
        的背叛重复一次就从 5 直接顶满 10)。旧版此函数有个 extra_importance
        参数但函数体硬编码 +1 从不读取 (M6 死参数), 调用方传的值被静默丢弃,
        现已删除, 语义在此显式固定。返回新 importance。
        """
        with self._lock:
            row = self._conn.execute(
                "SELECT importance FROM memory WHERE id = ?", (mem_id,)
            ).fetchone()
            if row is None:
                raise ValueError(f"观察 {mem_id} 不存在")
            new_imp = min(10.0, row[0] + 1.0)
            with self._conn:
                self._conn.execute(
                    "UPDATE memory SET last_accessed = ?, importance = ? "
                    "WHERE id = ?", (now, new_imp, mem_id))
            return new_imp

    def all_invalid(self) -> list[MemoryRecord]:
        """取全部已失效记忆 (冲突失效), 按时间排序, 供审查。

        注意: 遗忘改为降权后不再产生失效记录, 这里只剩冲突失效的反思。"""
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM memory WHERE valid = 0 ORDER BY timestamp, id"
            ).fetchall()
        cols = ("id", "type", "content", "timestamp", "importance", "player_id",
                "evidence", "confidence", "valid", "last_accessed",
                "base_confidence")
        return [MemoryRecord(**{**dict(zip(cols, r)),
                                "evidence": json.loads(r[6] or "[]")})
                for r in rows]

    # ------------------------------------------------------------------ 遗忘
    def decay_and_forget(self, now: float,
                         half_lives: dict[str, float] | None = None
                         ) -> list[int]:
        """时间遗忘 (部分衰减降权, 不删除): 把每条未受保护记忆的 importance
        乘以衰减因子, 渐近降到 MIN_IMPORTANCE 为止, 返回被降权的 id。

        importance *= 0.5 ** (age / half_life), 其中
          age = now - max(timestamp, last_accessed or timestamp)
                (被回忆过 / merge 刷新的记忆衰减更慢, 抗遗忘)
        记忆**保留** (valid 恒 1), 只降 importance —— 检索 importance 维随之
        跌出前排, 但仍可被检索, 被回忆又能升回。这是"降权"不是"抹除"。
        保护: 被有效反思引用为证据的观察不降权 —— 它已固化为高阶认知,
        降了它会削弱反思的证据链。保护集按当前有效反思快照计算。
        """
        hl = half_lives or FORGET_HALF_LIVES
        mems = self.all_valid()
        if not mems:
            return []
        # 保护集: 有效反思的证据 id (反思只引用观察, 见 reflection.py)
        protected: set[int] = set()
        for m in mems:
            if m.type == "reflection" and m.evidence:
                protected.update(m.evidence)
        downweighted: list[int] = []
        for m in mems:
            if m.type == "observation" and m.id in protected:
                continue
            anchor = max(m.timestamp,
                         m.last_accessed if m.last_accessed is not None
                         else m.timestamp)
            age = max(0.0, now - anchor)
            factor = 0.5 ** (age / hl.get(m.type, 48.0))
            new_imp = max(MIN_IMPORTANCE, m.importance * factor)
            if new_imp < m.importance - 1e-9:   # importance 实际下调
                self._set_importance(m.id, new_imp)
                downweighted.append(m.id)
        return downweighted

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
