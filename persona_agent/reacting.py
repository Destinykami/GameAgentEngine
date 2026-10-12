"""反应决策: 决定 NPC 是否响应环境事件, 以及响应后如何权衡。

核心是把"目标持续性 vs 行为灵活性"的权衡显式化为效用函数:

    U(a) = w_social · V_social(a) + w_goal · V_goal(a) − C_interrupt(a)

- w_social / w_goal 来自人格特质 (social / goal_oriented)。
- V_social / V_goal 由事件类型决定 (派对邀请 → 社交价值高; 备考被打断 → 目标价值高)。
- C_interrupt 是打断当前计划的代价。
- 关系状态 (对当前玩家的信任度) 会调制 w_social: 信任的人的邀请更可能被接受。

这正是"千人千面"在反应层的体现: 同一个邀请, 对信任的友善玩家接受, 对警惕的玩家拒绝。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from .memory import MemoryStore
from .reflection import TRUST_WORDS, DISTRUST_WORDS

# 事件价值表: 事件关键词 → (社交价值, 目标价值, 打断代价)
EVENT_VALUES = {
    "邀请": (8.0, 1.0, 3.0),    # 派对/聚会邀请: 社交价值高
    "派对": (8.0, 1.0, 3.0),
    "聚会": (8.0, 1.0, 3.0),
    "研究": (1.0, 8.0, 6.0),    # 研究/备考: 目标价值高, 打断代价高
    "备考": (1.0, 8.0, 6.0),
    "作曲": (1.0, 8.0, 6.0),
    "工作": (1.0, 6.0, 4.0),
    "聊天": (6.0, 1.0, 1.0),    # 闲聊: 社交中等, 打断代价低
}
DEFAULT_VALUE = (3.0, 3.0, 2.0)


@dataclass
class ReactionDecision:
    react: bool
    action: str
    utility: float
    reason: str


class ReactionDecider:
    """基于人格 + 关系状态 + 当前计划的反应决策。"""

    def __init__(self, store: MemoryStore) -> None:
        self._store = store

    # -------------------------------------------------------- 关系信任度
    def relationship_trust(self, player_id: str) -> float:
        """计算对该玩家的信任度, 范围 -1..1。

        基于关系记忆: 信任类词 +1, 警惕类词 -1, 归一化。
        """
        rel = self._store.all_valid(player_id=player_id)
        if not rel:
            return 0.0
        # 词表含单字与双字形态: 事件措辞用 "帮"/"骗"/"偷" 还是 "帮助"/"欺骗"/"撒谎" 都能识别
        pos = sum(1 for m in rel if any(w in m.content for w in TRUST_WORDS + ("帮助", "帮", "感谢")))
        neg = sum(1 for m in rel if any(w in m.content for w in DISTRUST_WORDS + ("背叛", "欺骗", "撒谎", "骗", "偷")))
        total = pos + neg
        if total == 0:
            return 0.0
        return (pos - neg) / total

    # -------------------------------------------------------- 反应决策
    def decide(self, event: str, player_id: str,
               persona_traits: dict[str, float],
               current_plan: str = "") -> ReactionDecision:
        """决定是否响应事件并给出行动。"""
        v_social, v_goal, c_interrupt = self._lookup_value(event)
        trust = self.relationship_trust(player_id)
        # 信任度调制社交权重: 信任 → 更愿社交; 警惕/背叛 → 社交价值大幅打折。
        # trust∈[-1,1] → [0, 2], 背叛者(trust≈-1)的社交价值被压到几乎为零。
        trust_mod = max(0.0, 1.0 + trust)
        w_social = persona_traits.get("social", 0.5) * trust_mod
        w_goal = persona_traits.get("goal_oriented", 0.5)

        utility = w_social * v_social + w_goal * v_goal - c_interrupt
        # 如果当前正忙重要的计划, 打断代价上升
        if current_plan and any(k in current_plan for k in ("研究", "备考", "作曲")):
            utility -= 2.0

        react = utility >= 0.0
        if react:
            action = f"接受并参与: {event}"
            reason = f"效用 {utility:.2f} ≥ 0 (社交权重{w_social:.2f}, 目标权重{w_goal:.2f}, 信任{trust:+.2f})"
        else:
            action = f"婉拒: {event}, 继续当前安排"
            reason = f"效用 {utility:.2f} < 0 (目标价值高或信任不足)"
        return ReactionDecision(react=react, action=action,
                                utility=utility, reason=reason)

    # --------------------------------------------------------------- 内部
    @staticmethod
    def _lookup_value(event: str) -> tuple[float, float, float]:
        for key, val in EVENT_VALUES.items():
            if key in event:
                return val
        return DEFAULT_VALUE
