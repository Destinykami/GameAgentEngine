"""记忆记录契约；无数据库、向量或认知运行依赖。"""

from __future__ import annotations

from dataclasses import dataclass, field

@dataclass
class MemoryRecord:
    content: str
    timestamp: float
    importance: float = 5.0
    type: str = "observation"          # observation | reflection | plan | episode | identity
    player_id: str | None = None
    evidence: list[int] = field(default_factory=list)
    confidence: float = 1.0            # 当前置信度 (反思会被冲突衰减)
    base_confidence: float = 1.0       # 创建时的初始置信度 (幂等衰减的重算基准)
    # 衰减的起始基线 (E1 幂等水位, 同 base_confidence 思路): 重要性从这条基线按
    # 0.5**(age/hl) 重算, 重扫不漂移不复合。默认 None → add() 回退到 importance,
    # 所以只设 importance 的调用方 (observe/_save_plan/测试) 自动正确; merge 提升
    # importance 时会同步抬高这条基线 (合并是真实重要性事件, 衰减不能把增益抹掉)。
    base_importance: float | None = None
    valid: bool = True
    last_accessed: float | None = None
    hearsay: bool = False              # S4: 传闻记忆 (非亲见, 检索按 hop 打折)
    hop: int = 0                       # S4: 传播跳数 (0=亲见, 上限 HEARSAY_MAX_HOP)
    consolidated: bool = False         # M1: 已被固化进情节摘要 (仍 valid 可检索, 退出冲突扫描)
    # F2-1: 上次 importance 强化时间 (merge 限速); None = 用 timestamp 兜底
    last_reinforced: float | None = None
    id: int | None = None              # 由数据库分配


