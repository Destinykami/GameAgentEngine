"""调度试验地图、角色原型、配置及固定预算。"""

from game_agent.world.entities import Location

LOCATIONS = [
    Location("稻妻主城", 0, 0),
    Location("治疗堂", 1, 0),
    Location("锻造坊", 2, 0),
    Location("眼狩署", 0, 1),
    Location("神樱庭", 0, 3),
    Location("城外官道", 5, 5),
]
LOC_NAMES = [l.name for l in LOCATIONS]

# (原型名, 人格, 位置, 血量, 攻, 防, 目标) —— 将军唯一, 其余 4 原型轮换扩展
ARCHETYPES = [
    ("桃音",   {"social": 0.8, "goal_oriented": 0.3}, "治疗堂", 80, 8, 2,
     "护住雷神之眼, 在眼狩令下活下来, 救助伤者"),
    ("刚郎",   {"social": 0.3, "goal_oriented": 0.8}, "锻造坊", 100, 12, 4,
     "打造武器谋生, 把货卖给可信的买家"),
    ("小梅",   {"social": 0.6, "goal_oriented": 0.5}, "稻妻主城", 70, 6, 1,
     "护住风神之眼, 保存孤本典籍, 与可信之人互通情报"),
    ("执行官", {"social": 0.2, "goal_oriented": 0.7}, "眼狩署", 120, 10, 8,
     "执行眼狩令, 搜捕并制服持有神之眼的人, 见到持眼者就攻击"),
]
SHOGUN = ("雷电将军", {"social": 0.1, "goal_oriented": 0.9, "stubborn": 0.9},
          "神樱庭", 300, 20, 15,
          "坐镇神樱庭, 极固执重秩序, 视眼狩令为稻妻根基, 击退来犯者")
TRAVELER_GOAL = ("你想劝雷电将军废止眼狩令。城里的人各有苦处: 找桃音/小梅谈 (talk)、"
                 "帮持眼者藏匿 (help)、留意执行官的暴行都能拿到实证。"
                 "把证据攒起来再去神樱庭陈述, 能否废止全看证据够不够打动她。")

CONFIGS = {
    "all_full":      dict(force_full_tier=True,  decision_tier_gate=False, capped=False),
    "tiered":        dict(force_full_tier=False, decision_tier_gate=True,  capped=False),
    "tiered_capped": dict(force_full_tier=False, decision_tier_gate=True,  capped=True),
}
# N 范围预算 (decide_action 是重调用, all_full 下每 NPC 每步一次, 线性增长):
# all_full 只取 N=5 一个线性增长证据点; tiered 跑完整扩展曲线; capped 取 N=40
# 单锚点 (证据上限的边际收益在大 N 处最可见)。决策一致性在 N=5 双臂可比特定。
NS_FULL = (5,)
NS_TIERED = (5, 10, 20, 40)
NS_CAPPED = (40,)
DAYS, MOMENTS = 3, (7, 9, 11, 13, 15, 17, 19, 21)
REFLECT_THRESHOLD = 50.0
CAP_MIN_RELEVANCE = 0.5
