"""记忆阈值、合并与遗忘策略；只处理传入记录快照。"""

from __future__ import annotations

from collections.abc import Iterator, Sequence

from .models import MemoryRecord

RECENCY_DECAY = 0.995
ALPHA_RECENCY = 1.0
ALPHA_IMPORTANCE = 1.0
ALPHA_RELEVANCE = 1.0

# 观察层去重: 同玩家的近义观察 (>= 阈值) 合并而非重复入库。
# 观察比反思更公式化、近义重复更多。反思去重 (E6) 从 0.95 降到 0.92 后,
# 两层阈值对齐到 0.92 —— 观察层本就取这个值, 保持一致。
OBS_DEDUP_THRESHOLD = 0.92

# 合并强化限速 (F2-1): 同一条观察反复"发生"时, importance 每受一次 merge 就
# +1 会把在场观察顶满 10 (世界层每步 perceive 都会 merge 一次)。重复仍是
# 记忆强化, 但 importance 强化按游戏时间窗限速: 只有距上次强化 >= 6h 才 +1,
# 其他 merge 只刷新 last_accessed (recency 语义不变)。
MERGE_REINFORCE_INTERVAL = 6.0

# 遗忘 = 部分衰减降权 (不直接删除): importance *= 0.5 ** (age / half_life),
# 渐近降到 MIN_IMPORTANCE 为止, 记忆**保留**(valid 恒为 1), 只是 importance
# 被调低。检索的 importance 维用 importance/10, 所以老记忆自然跌出前排,
# 但仍在库里 —— 被回忆(last_accessed 刷新)或 merge 时又能升回来。
# - age: 距 max(timestamp, last_accessed) 的小时数 —— 被回忆过的记忆衰减更慢
# - 半衰期: 原始观察最先淡去, 反思(高阶认知)留存最久, 计划隔夜即过期
# - FORGET_FLOOR 是强度(0-1)下限; MIN_IMPORTANCE = FORGET_FLOOR*10 是
#   对应的 importance(0-10)下限 —— 降权到此为止, 不再删。
# 传闻折扣 (S4): 传闻记忆的检索分数按传播跳数打折 (每跳 ×0.8) —— 谣言不是亲见,
# 离源头越远, 检索排名越低。非传闻记忆 (hop=0) 折扣恒 1.0, 现行为不变。
HEARSAY_DECAY = 0.8
# 传闻链上限: 超过 3 跳的转述不再入库 (谣言到第三手就该停, 否则世界会被
# "听说听说听说……" 灌满)。
HEARSAY_MAX_HOP = 3

FORGET_FLOOR = 0.15
MIN_IMPORTANCE = FORGET_FLOOR * 10.0   # = 1.5, importance 降权下限
FORGET_HALF_LIVES: dict[str, float] = {
    "observation": 48.0,   # ~2 天: 没被固化、没被回忆的原始事件先降权
    "reflection": 168.0,   # ~1 周: 高阶认知降权最慢
    "episode": 168.0,      # ~1 周: 固化后的情节摘要与反思同档
    "identity": 336.0,     # ~2 周: 身份层信念最稳定
    "plan": 24.0,          # ~1 天: 计划隔夜即降权
}


def apply_observation_merge(rec: MemoryRecord, now: float, *,
                            new_hearsay: bool | None = None, new_hop: int = 0,
                            new_content: str | None = None,
                            reinforce_interval: float = MERGE_REINFORCE_INTERVAL
                            ) -> None:
    """更新分离于数据库的记录快照；外部写入与缓存失效由调用方处理。"""
    reinforce = (rec.last_reinforced is None
                 or now - rec.last_reinforced >= reinforce_interval)
    new_imp = min(10.0, rec.importance + 1.0) if reinforce else rec.importance
    rec.base_importance = (new_imp if reinforce
                           else (rec.base_importance if rec.base_importance is not None
                                 else rec.importance))
    rec.importance = new_imp
    if reinforce:
        rec.last_reinforced = now
    if new_content is not None and len(new_content) > len(rec.content):
        rec.content = new_content
    if new_hearsay is not None:
        if rec.hearsay and new_hearsay:
            rec.hop = min(rec.hop, new_hop)
        else:
            rec.hearsay, rec.hop = False, 0
    rec.last_accessed = now


def decay_updates(records: Sequence[MemoryRecord], now: float,
                  half_lives: dict[str, float], floor: float
                  ) -> Iterator[tuple[MemoryRecord, float]]:
    """按有效记录快照计算降权，不修改记录、不写库。"""
    protected = set()
    for rec in records:
        if rec.type == "reflection" and rec.evidence:
            protected.update(rec.evidence)
    for rec in records:
        if rec.type == "observation" and rec.id in protected:
            continue
        anchor = max(rec.timestamp, rec.last_accessed if rec.last_accessed is not None
                     else rec.timestamp)
        age = max(0.0, now - anchor)
        factor = 0.5 ** (age / half_lives.get(rec.type, 48.0))
        base = rec.base_importance if rec.base_importance is not None else rec.importance
        importance = max(floor, base * factor)
        if importance < rec.importance - 1e-9:
            yield rec, importance
