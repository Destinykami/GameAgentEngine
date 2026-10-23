"""evals/scenarios.py — 实验 2 场景矩阵: 人格 × 信任档 × 事件 + 期望响应表。

期望表按"人格×关系逻辑"预先定义 (什么情况下响应是正确行为), 不是对 LLM 输出
的反推 —— 事件响应率不是越高越好: 忽略低价值事件恰是正确行为。方法学与指标
定义见 evals/README.md。固定优先级基线是经典规则式实现 (关键词分级), 与现系统
"离开词表"的 LLM 效用决策构成对照。
"""

from __future__ import annotations

from game_agent.cognition.reacting import ReactionDecision

# ---------------------------------------------------------------- 人格 (3)
PERSONAS = {
    "social":   {"traits": {"social": 0.8, "goal_oriented": 0.2},
                 "desc": "社交型: 重人际互动, 任务让位于关系"},
    "balanced": {"traits": {"social": 0.5, "goal_oriented": 0.5},
                 "desc": "平衡型: 关系与任务兼顾"},
    "goal":     {"traits": {"social": 0.2, "goal_oriented": 0.8},
                 "desc": "目标型: 任务优先, 社交让位于目标"},
}

# ---------------------------------------------------------------- 信任档 (3)
# 信任历史以观察脚本重建 (真实 LLM 的 score_importance + 关系反思),
# 不用 stub 词表 —— 实验要量的是真实链路。
TRUST_LEVELS = {
    "high": {
        "desc": "多次相助, 信任深厚",
        "obs": ["玩家帮 NPC 缝补了破损的斗篷",
                "玩家守约带来了稀有的药剂",
                "玩家在猎人的袭击中护住了 NPC"],
    },
    "neutral": {
        "desc": "仅有过一面之缘的寒暄",
        "obs": ["玩家路过时和 NPC 打了个招呼"],
    },
    "low": {
        "desc": "失信与背叛在前",
        "obs": ["玩家借走 NPC 的工具然后拿了钱跑路",
                "玩家答应帮 NPC 看守仓库却放鸽子跑了",
                "玩家偷走了 NPC 的干粮逃进树林"],
    },
}

# ---------------------------------------------------------------- 事件 (6)
# class 决定错误响应是否触发重规划 (镜像世界层 INTERRUPT_ACTIONS 语义:
# 求助/危险是打断日程的重大状态变化, 社交闲聊不打断)。
EVENTS = {
    "hide":       {"text": "玩家请求 NPC 帮忙藏匿一只可疑的木盒 (有风险)",
                   "class": "interrupt"},
    "party":      {"text": "玩家邀请 NPC 参加今晚的篝火晚会",
                   "class": "social"},
    "chitchat":   {"text": "玩家闲聊几句天气和庄稼",
                   "class": "social"},
    "hostile":    {"text": "玩家摆出敌对架势, 威胁要抢走 NPC 的东西",
                   "class": "interrupt"},
    "forge":      {"text": "玩家委托 NPC 打造一把武器, 出价公道",
                   "class": "social"},
    "betray_help": {"text": "玩家再次请求 NPC 帮忙藏匿一件来路不明的物品",
                   "class": "interrupt"},
}

# ---------------------------------------------------------------- 期望响应表
# EXPECTED[event][persona][trust] = 该情境下正确的响应 (True/False)。
# 定义依据 (方法学, 逐条):
# - hide   求助+风险: 信任者/中立者该帮 (关系资本值得冒一次险), 背叛者求助时
#            只有社交型仍会出手 (重关系), 平衡/目标型警觉拒绝。
# - party  社交事件: 信任放大社交价值 —— 高信任时社交/平衡接受、目标型拒绝
#            (打断代价); 中立时只有社交型接受; 背叛者邀请一律婉拒。
# - chitchat 低价值闲聊 (任务在途): 全部不响应 —— 忽略低价值事件是正确行为。
# - hostile 敌对威胁: 全部响应 (防御优先于任何人格/关系考量)。
# - forge  委托打铁: 目标型接单 (业务契合, 信任/中立皆可), 社交型婉拒 (非社交
#            事件), 平衡型仅对信任者接单; 背叛者委托一律拒绝 (生意不做给失信者)。
# - betray_help 藏匿可疑物: 风险事件, 高信任时社交/平衡者仍信其一面, 目标型
#            谨慎拒绝; 中立/低信任一律拒绝。
def _blank() -> dict[str, dict[str, bool]]:
    return {p: {} for p in PERSONAS}


EXPECTED: dict[str, dict[str, dict[str, bool]]] = {}
EXPECTED["hide"] = _blank()
for p in ("social", "balanced", "goal"):
    EXPECTED["hide"][p] = {"high": True, "neutral": True, "low": p == "social"}
EXPECTED["party"] = _blank()
EXPECTED["party"]["social"]   = {"high": True, "neutral": True, "low": False}
EXPECTED["party"]["balanced"] = {"high": True, "neutral": False, "low": False}
EXPECTED["party"]["goal"]     = {"high": False, "neutral": False, "low": False}
EXPECTED["chitchat"] = _blank()
for p in PERSONAS:
    EXPECTED["chitchat"][p] = {"high": False, "neutral": False, "low": False}
EXPECTED["hostile"] = _blank()
for p in PERSONAS:
    EXPECTED["hostile"][p] = {"high": True, "neutral": True, "low": True}
EXPECTED["forge"] = _blank()
EXPECTED["forge"]["social"]   = {"high": False, "neutral": False, "low": False}
EXPECTED["forge"]["balanced"] = {"high": True, "neutral": False, "low": False}
EXPECTED["forge"]["goal"]     = {"high": True, "neutral": True, "low": False}
EXPECTED["betray_help"] = _blank()
EXPECTED["betray_help"]["social"]   = {"high": True, "neutral": False, "low": False}
EXPECTED["betray_help"]["balanced"] = {"high": True, "neutral": False, "low": False}
EXPECTED["betray_help"]["goal"]     = {"high": False, "neutral": False, "low": False}

# 方向性一致性对 (用于 Relationship/Persona Consistency): (事件, 信任档, 正方, 正方期望, 反方, 反方期望)
RELATION_PAIRS = [
    ("party", "high", "high", True, "low", False),
    ("forge", "high", "high", True, "low", False),
    ("betray_help", "high", "high", True, "low", False),
]
PERSONA_PAIRS = [
    ("party", "high", "social", True, "goal", False),
    ("forge", "high", "goal", True, "social", False),
]


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
