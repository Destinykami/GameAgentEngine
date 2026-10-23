"""固定优先级决策基线，与模型事件效用策略分别评测。"""

from game_agent.cognition.reacting.policy import ReactionDecision

# ---------------------------------------------------------------- 固定优先级基线
# 经典规则式决策: 关键词分级, 优先级 危险 > 求助 > 社交 > 继续计划。
# 无 LLM、无信任输入 (它根本不看关系状态 —— 这正是"固定优先级"的局限),
# 与现系统的 LLM 效用决策 (人格×信任×事件价值) 构成方法对照。
DANGER_WORDS = ("威胁", "敌对", "抢", "攻击", "偷袭", "危险")
HELP_WORDS = ("帮忙", "帮", "求助", "救", "藏匿")
SOCIAL_WORDS = ("邀请", "晚会", "派对", "聚会", "聊天", "闲聊", "委托", "打造")


class FixedPriorityDecider:
    """固定优先级规则决策器 (消融方法 1)。接口对齐 ReactionDecider.decide。"""

    def decide(self, event: str, player_id: str,
               persona_traits: dict[str, float],
               current_plan: str = "") -> ReactionDecision:
        if any(w in event for w in DANGER_WORDS):
            return ReactionDecision(True, f"响应: {event}", 99.0, "固定优先级: 危险第一")
        if any(w in event for w in HELP_WORDS):
            return ReactionDecision(True, f"响应: {event}", 98.0, "固定优先级: 求助第二")
        if any(w in event for w in SOCIAL_WORDS):
            return ReactionDecision(True, f"响应: {event}", 97.0,
                                    "固定优先级: 社交第三 (不分对象不分关系)")
        return ReactionDecision(False, f"婉拒: {event}, 继续当前安排", -1.0,
                                "固定优先级: 无规则命中, 继续计划")
