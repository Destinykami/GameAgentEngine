"""纯记忆排序：输入候选与相似度，输出分数和记录，不产生访问副作用。"""

from __future__ import annotations

from collections.abc import Sequence

from .models import MemoryRecord
from .policies import (ALPHA_IMPORTANCE, ALPHA_RECENCY, ALPHA_RELEVANCE,
                            HEARSAY_DECAY, RECENCY_DECAY)


def rank_memories(records: Sequence[MemoryRecord], similarities: Sequence[float],
                  now: float, *, top_k: int = 8,
                  include_player: str | None = None, min_score: float = 0.0,
                  min_relevance: float = 0.0, recency_decay: float = RECENCY_DECAY,
                  weights: tuple[float, float, float] =
                  (ALPHA_RECENCY, ALPHA_IMPORTANCE, ALPHA_RELEVANCE),
                  hearsay_decay: float = HEARSAY_DECAY
                  ) -> list[tuple[float, MemoryRecord]]:
    cands = list(records)
    relevance = list(similarities)
    if not cands:
        return []
    # 计算原始分数
    recs = [c.last_accessed if c.last_accessed is not None else c.timestamp
            for c in cands]
    deltas = [max(0.0, now - t) for t in recs]
    recency = [recency_decay ** d for d in deltas]
    importance = [c.importance / 10.0 for c in cands]

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

    # importance 是绝对显著度，不随候选集合变化而重新拉伸。
    r_norm, s_norm = norm(recency), norm(relevance)
    raw = []
    for c, r, i, s in zip(cands, r_norm, importance, s_norm):
        score = (weights[0] * r + weights[1] * i +
                 weights[2] * s)
        # 置信度折减 (H2): 被冲突衰减的反思按信念强度打折 —— check_conflicts
        # 的幂等衰减每多一条冲突证据就折半一次, 这里乘 confidence 与之一一对应,
        # 削弱的信念检索排名随之下降 (博客 2.2.5 "防不可靠推断被放大" 的落点)。
        # 观察/计划的 confidence 恒 1.0, 不受影响。
        score *= c.confidence
        # 传闻折扣 (S4): 按传播跳数打折 —— 亲见 (hop=0) 恒 1.0, 现行为不变。
        if c.hearsay and c.hop > 0:
            score *= hearsay_decay ** c.hop
        # 千人千面: 属于当前玩家的记忆获得额外加权
        if include_player and c.player_id == include_player:
            score += 0.5
        raw.append((score, c))

    raw.sort(key=lambda x: x[0], reverse=True)
    return [(score, rec) for score, rec in raw[:top_k] if not score < min_score]
