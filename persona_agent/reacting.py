"""反应决策: 决定 NPC 是否响应环境事件, 以及响应后如何权衡。

核心是把"目标持续性 vs 行为灵活性"的权衡显式化为效用函数:

    U(a) = w_social · V_social(a) + w_goal · V_goal(a) − C_interrupt(a)

- w_social / w_goal 来自人格特质 (social / goal_oriented)。
- V_social / V_goal / C_interrupt 由 **LLM 判断** (score_event), 对任意事件
  (含没枚举过的) 都能给出价值, 取代了原来的关键词死表。判断结果按
  (事件, 计划) 缓存, 同一情境不重复调 LLM —— 反应是高频路径, 必须控成本。
- 关系状态 (对当前玩家的信任度) 调制 w_social: 信任的人的邀请更可能被接受。

这正是"千人千面"在反应层的体现: 同一个邀请, 对信任的友善玩家接受,
对警惕的玩家拒绝。
"""

from __future__ import annotations

from dataclasses import dataclass

from .llm import LLMClient
from .memory import MemoryStore
from .reflection import TRUST_WORDS, DISTRUST_WORDS


@dataclass
class ReactionDecision:
    react: bool
    action: str
    utility: float
    reason: str


class ReactionDecider:
    """基于人格 + 关系状态 + 当前计划 + LLM 事件价值判断的反应决策。"""

    def __init__(self, store: MemoryStore, llm: LLMClient) -> None:
        self._store = store
        self._llm = llm
        # 事件价值缓存: (事件文本, 当前计划) → (v_social, v_goal, c_interrupt)。
        # 反应是高频路径, 同一情境不重复调 LLM。
        self._value_cache: dict[tuple[str, str], tuple[float, float, float]] = {}

    # -------------------------------------------------------- 关系信任度
    def relationship_trust(self, player_id: str) -> float:
        """计算对该玩家的信任度, 范围 -1..1。基于关系记忆词表计数 (启发式)。"""
        rel = self._store.all_valid(player_id=player_id)
        if not rel:
            return 0.0
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
        """决定是否响应事件并给出行动。事件价值由 LLM 判断 (带缓存)。"""
        v_social, v_goal, c_interrupt = self._score_event(
            event, persona_traits, current_plan)
        trust = self.relationship_trust(player_id)
        # 信任度调制社交权重: 信任 → 更愿社交; 警惕/背叛 → 社交价值大幅打折。
        # trust∈[-1,1] → [0, 2], 背叛者(trust≈-1)的社交价值被压到几乎为零。
        trust_mod = max(0.0, 1.0 + trust)
        w_social = persona_traits.get("social", 0.5) * trust_mod
        w_goal = persona_traits.get("goal_oriented", 0.5)

        utility = w_social * v_social + w_goal * v_goal - c_interrupt
        react = utility >= 0.0
        if react:
            action = f"接受并参与: {event}"
            reason = (f"效用 {utility:.2f} ≥ 0 (LLM判价值 社交{v_social:.0f}/"
                      f"目标{v_goal:.0f}/打断{c_interrupt:.0f}, "
                      f"社交权重{w_social:.2f}, 目标权重{w_goal:.2f}, 信任{trust:+.2f})")
        else:
            action = f"婉拒: {event}, 继续当前安排"
            reason = (f"效用 {utility:.2f} < 0 (LLM判价值 社交{v_social:.0f}/"
                      f"目标{v_goal:.0f}/打断{c_interrupt:.0f}, "
                      f"目标价值高或信任不足)")
        return ReactionDecision(react=react, action=action,
                                utility=utility, reason=reason)

    # --------------------------------------------------------------- 内部
    def _score_event(self, event: str, persona_traits: dict[str, float],
                     current_plan: str) -> tuple[float, float, float]:
        """LLM 判断事件价值, 按 (事件, 计划) 缓存。"""
        key = (event, current_plan)
        if key in self._value_cache:
            return self._value_cache[key]
        val = self._llm.score_event(event, persona_traits, current_plan)
        self._value_cache[key] = val
        return val

    def clear_cache(self) -> None:
        self._value_cache.clear()
