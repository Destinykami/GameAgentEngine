"""world_sim: 稻妻城·眼狩令 —— 一周世界模拟 (看每个 agent 认知深化 + 世界演化)。

旅行者跨 7 天穿行城中: 帮桃音藏眼 (从试探到生死相托)、与刚郎务实交易 (从生分到
热络)、盘问执行官 (从试探到摊牌)、帮小梅 (给她一段关系)、雷电将军始终疏离。世界
事件逐级升级 (眼狩令生效 → 搜捕 → 大搜捕 → 最后清剿)。

**反思阈值调低到 25** (默认 150 同论文, 这里调低让一周的中等事件量就能触发自我
反思 —— 展示 agent 的高阶自我认知)。每天输出每个 NPC 的认知快照 (档位/信任/记忆
条数/自我反思/关系反思), 最后打印 7 天信任轨迹 + 记忆增长 + 遗忘证据。

全程真实 LLM。世界状态存 data/sim/world.db, 每 NPC 独立 data/sim/<name>.db。
跑法: python examples/world_sim.py   (需 LLM 可达, 约 10-15 分钟)
"""

from __future__ import annotations

import os
import shutil
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from persona_agent import World, Location, RealLLM, make_embedder

DATA = os.path.join(os.path.dirname(__file__), "..", "data", "sim")
REFLECT_THRESHOLD = 25.0   # 调低 (默认 150), 让一周的事件量触发自我反思

LOCATIONS = [
    Location("稻妻主城", 0, 0),
    Location("治疗堂", 1, 0),
    Location("锻造坊", 2, 0),
    Location("眼狩署", 0, 1),
    Location("神樱庭", 0, 3),
    Location("城外官道", 5, 5),
]

NPCS = [
    ("桃音",   {"social": 0.8, "goal_oriented": 0.3}, "治疗堂",    "疗愈者·雷神之眼"),
    ("刚郎",   {"social": 0.3, "goal_oriented": 0.8}, "锻造坊",    "铁匠·火神之眼"),
    ("小梅",   {"social": 0.6, "goal_oriented": 0.5}, "稻妻主城",  "学者·风神之眼"),
    ("执行官", {"social": 0.2, "goal_oriented": 0.7}, "眼狩署",    "眼狩令执行官"),
    ("雷电将军", {"social": 0.1, "goal_oriented": 0.9}, "神樱庭",  "将军·永恒"),
]


def banner(t: str) -> None:
    print("\n" + "═" * 78)
    print(t)
    print("═" * 78)


def sub(t: str) -> None:
    print("\n" + "─" * 78)
    print(t)
    print("─" * 78)


def tiers_str(tiers: dict) -> str:
    return "  ".join(f"{n}={t}" for n, t in tiers.items())


def say(npc_name: str, traveler_says: str, npc_replies: str) -> None:
    """打印一段对话: 旅行者说 (脚本驱动, 是喂给 speak 的输入) + NPC 回
    (NPC 自己用 LLM 非全知生成, 只用它自己的记忆流)。

    npc_name 是对话对象 (回复由谁生成、第二句标谁), 不是第一句的说话人。
    """
    print(f"   旅行者: {traveler_says}")
    print(f"   {npc_name}: {npc_replies}")


def snapshot(w: World, day_label: str) -> None:
    sub(f"{day_label} — 每个 NPC 的认知表现")
    for name, _, _, role in NPCS:
        npc = w.npc(name)
        loc = w.entities[name].location.name
        trust = npc.trust_toward("旅行者")
        n_obs = len(npc.store.all_valid(types=["observation"]))
        refl = npc.store.all_valid(types=["reflection"])
        self_refl = [r.content for r in refl if r.player_id is None]
        rel_refl = [r.content for r in refl if r.player_id == "旅行者"]
        last_self = self_refl[-1] if self_refl else "· (尚未累积到自我反思阈值)"
        last_rel = rel_refl[-1] if rel_refl else "· (尚未建立对旅行者的关系认知)"
        print(f"\n[{loc}] {name} ({role})")
        print(f"   档位={npc._tier:<11} 信任→旅行者={trust:+.2f}   "
              f"记忆: 观察{n_obs} / 反思{len(refl)}")
        print(f"   自我反思: {last_self}")
        print(f"   对旅行者的关系反思: {last_rel}")


def trust_row(w: World) -> dict:
    return {name: round(w.npc(name).trust_toward("旅行者"), 2)
            for name, _, _, _ in NPCS}


def main() -> int:
    shutil.rmtree(DATA, ignore_errors=True)
    os.makedirs(DATA, exist_ok=True)
    llm = RealLLM()
    emb = make_embedder()
    w = World("稻妻城", LOCATIONS, path=os.path.join(DATA, "world.db"))
    for name, persona, loc, _ in NPCS:
        w.add_npc(name, persona, llm=llm, embedder=emb, data_dir=DATA,
                  location=loc, reflection_threshold=REFLECT_THRESHOLD)
    w.add_player("旅行者", "稻妻主城")
    trajectory: list[dict] = []

    # ============================ 第 1 天 ============================
    banner("第 1 天 07:00  眼狩令生效 (全图事件)")
    w.world_event("雷电将军颁布眼狩令: 全城神之眼一律收缴", now=7.0)
    s = w.step(7.0)
    print("档位:", tiers_str(s["tiers"]))
    for name, _, _, _ in NPCS:
        w.npc(name).generate_daily_plan(previous_day="", date="第1天", now=7.5)

    banner("第 1 天 09:00  旅行者到治疗堂, 初次帮桃音藏眼")
    w.move("旅行者", "治疗堂", now=9.0)
    w.npc("桃音").observe("旅行者帮 桃音 把雷神之眼藏进了地窖", 9.0, player_id="旅行者")
    w.step(9.0)
    say("桃音", "藏起神之眼, 他们会不会发现?",
        w.npc("桃音").speak("旅行者", "藏起神之眼, 他们会不会发现?", 9.5))

    banner("第 1 天 11:00  旅行者到锻造坊, 委托刚郎打造武器 (旅行者先开口谈委托)")
    w.move("旅行者", "锻造坊", now=11.0)
    w.npc("刚郎").observe("旅行者 找 刚郎 委托打造武器, 言谈务实, 公平交易", 11.0,
                          player_id="旅行者")
    w.step(11.0)
    # 旅行者开口委托 → 刚郎务实回应报价 (刚郎口吻由 LLM 生成)
    say("刚郎", "我想委托你打造一批武器, 工期和报酬怎么谈?",
        w.npc("刚郎").speak("旅行者", "我想委托你打造一批武器, 工期和报酬怎么谈?", 11.5))

    banner("第 1 天 20:00  旅行者离开稻妻城")
    w.move("旅行者", "城外官道", now=20.0)
    s = w.step(20.0)
    print("档位:", tiers_str(s["tiers"]), "(离开 → 全员 idle)")
    trajectory.append(trust_row(w))
    snapshot(w, "第 1 天结束 (20:00)")

    # ============================ 第 2 天 ============================
    banner("第 2 天 10:00  旅行者再到治疗堂, 更谨慎地帮桃音")
    w.move("旅行者", "治疗堂", now=34.0)
    w.npc("桃音").observe("旅行者 再次帮 桃音 转移雷神之眼, 这次藏得更隐蔽", 34.0,
                          player_id="旅行者")
    w.step(34.0)
    say("桃音", "这样下去, 带着神之眼还能安心生活吗?",
        w.npc("桃音").speak("旅行者", "这样下去, 带着神之眼还能安心生活吗?", 34.5))

    banner("第 2 天 14:00  旅行者回主城, 小梅打听眼狩令")
    w.move("旅行者", "稻妻主城", now=38.0)
    w.npc("小梅").observe("旅行者 找 小梅 打听眼狩令的动向, 二人交换情报", 38.0,
                          player_id="旅行者")
    w.step(38.0)
    say("小梅", "眼狩令这么下去, 我们还能保住自己的眼吗?",
        w.npc("小梅").speak("旅行者", "眼狩令这么下去, 我们还能保住自己的眼吗?", 38.5))

    banner("第 2 天 20:00  旅行者离开")
    w.move("旅行者", "城外官道", now=44.0)
    w.step(44.0)
    trajectory.append(trust_row(w))
    snapshot(w, "第 2 天结束 (20:00)")

    # ============================ 第 3 天 ============================
    banner("第 3 天 08:00  世界事件: 执行官搜捕全城神之眼")
    w.world_event("执行官带队搜捕全城的神之眼", now=56.0, at="眼狩署", radius=1.5)
    w.move("旅行者", "稻妻主城", now=56.5)
    s = w.step(56.5)
    print("档位:", tiers_str(s["tiers"]))

    banner("第 3 天 10:00  旅行者回访锻造坊, 谈加急 (旅行者先问上次那批货)")
    w.move("旅行者", "锻造坊", now=58.0)
    w.npc("刚郎").observe("刚郎 欣赏 旅行者 的务实, 主动多送了他一份材料", 58.0,
                          player_id="旅行者")
    w.step(58.0)
    # 旅行者问上次那批货 → 刚郎回应并主动加急 (刚郎口吻由 LLM 生成)
    say("刚郎", "上次那批货很称手, 这批能不能给我加急?",
        w.npc("刚郎").speak("旅行者", "上次那批货很称手, 这批能不能给我加急?", 58.5))

    banner("第 3 天 17:00  旅行者到眼狩署, 执行官盘问他 (旅行者先搭话)")
    w.move("旅行者", "眼狩署", now=65.0)
    w.npc("执行官").observe("旅行者 被目击帮助 桃音 藏匿神之眼", 65.0, player_id="旅行者")
    w.step(65.0)
    # 旅行者主动搭话 → 执行官顺势盘问藏匿 (执行官口吻由 LLM 生成)
    say("执行官", "我来看看眼狩署最近在忙什么, 眼狩令还要搜到什么程度?",
        w.npc("执行官").speak("旅行者", "我来看看眼狩署最近在忙什么, 眼狩令还要搜到什么程度?", 65.5))

    banner("第 3 天 20:00  旅行者离开")
    w.move("旅行者", "城外官道", now=68.0)
    w.step(68.0)
    trajectory.append(trust_row(w))
    snapshot(w, "第 3 天结束 (20:00)")

    # ============================ 第 4 天 ============================
    banner("第 4 天 10:00  旅行者到治疗堂, 桃音为旅行者疗伤 (旅行者先关心她)")
    w.move("旅行者", "治疗堂", now=94.0)
    w.npc("桃音").observe("桃音 为 旅行者 包扎伤口, 两人互相信任加深", 94.0,
                          player_id="旅行者")
    w.step(94.0)
    # 旅行者先关心桃音 → 桃音回应情义 (桃音口吻由 LLM 生成)
    say("桃音", "这次多亏你照应, 我没事, 你别担心。",
        w.npc("桃音").speak("旅行者", "这次多亏你照应, 我没事, 你别担心。", 94.5))

    banner("第 4 天 14:00  旅行者帮小梅抄录典籍 (旅行者先问抄书进度)")
    w.move("旅行者", "稻妻主城", now=98.0)
    w.npc("小梅").observe("旅行者 帮 小梅 抄录孤本典籍, 两人结下学缘", 98.0,
                          player_id="旅行者")
    w.step(98.0)
    # 旅行者先问抄书 → 小梅道谢 (小梅口吻由 LLM 生成)
    say("小梅", "帮你把那批孤本抄完了, 还顺利吧?",
        w.npc("小梅").speak("旅行者", "帮你把那批孤本抄完了, 还顺利吧?", 98.5))

    banner("第 4 天 20:00  旅行者离开")
    w.move("旅行者", "城外官道", now=104.0)
    w.step(104.0)
    trajectory.append(trust_row(w))
    snapshot(w, "第 4 天结束 (20:00)")

    # ============================ 第 5 天 ============================
    banner("第 5 天 08:00  世界事件: 执行官第二次大搜捕")
    w.world_event("执行官加大搜捕力度, 挨家挨户搜查神之眼", now=120.0,
                  at="眼狩署", radius=2.0)
    w.move("旅行者", "稻妻主城", now=120.5)
    w.step(120.5)

    banner("第 5 天 10:00  旅行者到锻造坊, 下加急订单 (旅行者先要加急)")
    w.move("旅行者", "锻造坊", now=122.0)
    w.npc("刚郎").observe("旅行者 下加急订单, 刚郎 连夜赶工相助", 122.0,
                          player_id="旅行者")
    w.step(122.0)
    # 旅行者先要加急 → 刚郎追问急用在哪 (刚郎口吻由 LLM 生成)
    say("刚郎", "这批货要加急, 三天内能赶出来吗?",
        w.npc("刚郎").speak("旅行者", "这批货要加急, 三天内能赶出来吗?", 122.5))

    banner("第 5 天 17:00  旅行者到眼狩署, 执行官因搜捕无果迁怒 (旅行者先问搜捕)")
    w.move("旅行者", "眼狩署", now=129.0)
    w.npc("执行官").observe("执行官 搜捕无果, 怀疑 旅行者 知情不报, 当面施压", 129.0,
                            player_id="旅行者")
    w.step(129.0)
    # 旅行者先问搜捕结果 → 执行官迁怒包庇 (执行官口吻由 LLM 生成)
    say("执行官", "搜了三天还没结果? 城里到底还有谁藏着神之眼?",
        w.npc("执行官").speak("旅行者", "搜了三天还没结果? 城里到底还有谁藏着神之眼?", 129.5))

    banner("第 5 天 20:00  旅行者离开")
    w.move("旅行者", "城外官道", now=132.0)
    w.step(132.0)
    trajectory.append(trust_row(w))
    snapshot(w, "第 5 天结束 (20:00)")

    # ============================ 第 6 天 ============================
    banner("第 6 天 10:00  旅行者到治疗堂, 桃音处境危急, 生死相托 (旅行者先关心她)")
    w.move("旅行者", "治疗堂", now=158.0)
    w.npc("桃音").observe("治疗堂被搜, 桃音 性命攸关, 把雷神之眼和安危都托付给 旅行者",
                          158.0, player_id="旅行者")
    w.step(158.0)
    # 旅行者先关心桃音安危 → 桃音托付眼和堂口 (桃音口吻由 LLM 生成)
    say("桃音", "清剿令都下了, 你和堂口这边还撑得住吗?",
        w.npc("桃音").speak("旅行者", "清剿令都下了, 你和堂口这边还撑得住吗?", 158.5))

    banner("第 6 天 14:00  旅行者回主城, 小梅担忧搜捕升级 (旅行者先问她撑不撑得住)")
    w.move("旅行者", "稻妻主城", now=162.0)
    w.npc("小梅").observe("小梅 忧惧搜捕升级, 向 旅行者 求助如何自保", 162.0,
                          player_id="旅行者")
    w.step(162.0)
    # 旅行者先问小梅撑不撑得住 → 小梅求助如何保眼 (小梅口吻由 LLM 生成)
    say("小梅", "搜捕越来越凶, 你那边还撑得住吗?",
        w.npc("小梅").speak("旅行者", "搜捕越来越凶, 你那边还撑得住吗?", 162.5))

    banner("第 6 天 20:00  旅行者离开")
    w.move("旅行者", "城外官道", now=168.0)
    w.step(168.0)
    trajectory.append(trust_row(w))
    snapshot(w, "第 6 天结束 (20:00)")

    # ============================ 第 7 天 ============================
    banner("第 7 天 08:00  世界事件: 最后清剿, 持眼者面临末路")
    w.world_event("雷电将军下令最后清剿: 限期交出神之眼, 逾期格杀", now=192.0)
    w.move("旅行者", "稻妻主城", now=192.5)
    s = w.step(192.5)
    print("档位:", tiers_str(s["tiers"]))
    for name, _, _, _ in NPCS:
        w.npc(name).generate_daily_plan(previous_day="第6天", date="第7天", now=193.0)

    banner("第 7 天 10:00  旅行者到眼狩署, 与执行官摊牌 (旅行者先问眼狩令)")
    w.move("旅行者", "眼狩署", now=194.0)
    w.npc("执行官").observe("旅行者 当面摊牌, 点破执行官包庇无果的窘境", 194.0,
                            player_id="旅行者")
    w.step(194.0)
    # 旅行者先问眼狩令还要搜多久 → 执行官摊牌质问 (执行官口吻由 LLM 生成)
    say("执行官", "眼狩令还要搜到什么时候? 你们就这么抓不完?",
        w.npc("执行官").speak("旅行者", "眼狩令还要搜到什么时候? 你们就这么抓不完?", 194.5))

    banner("第 7 天 14:00  旅行者到治疗堂, 陪桃音做最后准备 (旅行者先致谢)")
    w.move("旅行者", "治疗堂", now=198.0)
    w.npc("桃音").observe("旅行者 陪 桃音 做最后准备, 两人已生死与共", 198.0,
                          player_id="旅行者")
    w.step(198.0)
    # 旅行者先谢她一路辛苦 → 桃音回应不后悔 (桃音口吻由 LLM 生成)
    say("桃音", "清剿在即, 这一路辛苦你了。",
        w.npc("桃音").speak("旅行者", "清剿在即, 这一路辛苦你了。", 198.5))

    banner("第 7 天 20:00  旅行者离开稻妻城 (一周结束)")
    w.move("旅行者", "城外官道", now=204.0)
    s = w.step(204.0)
    print("档位:", tiers_str(s["tiers"]), "(离开 → 全员 idle)")
    trajectory.append(trust_row(w))
    snapshot(w, "第 7 天结束 (20:00)")

    banner("一周信任演化轨迹 (千人千面)")
    header = "   " + f"{'NPC':<8}" + "".join(f"{'D'+str(i):>8}" for i in range(1, 8))
    print(header)
    for name, _, _, _ in NPCS:
        row = f"   {name:<8}" + "".join(f"{trajectory[d][name]:>+8.2f}"
                                         for d in range(7))
        print(row)
    print("\n   桃音(受助→生死相托)信任一路升温 / 刚郎(务实交易)稳步上升 /")
    print("   小梅(好奇→学缘→求助)由 0 转正 / 执行官(藏匿→迁怒→摊牌)警惕 /")
    print("   雷电将军疏离 (从不接近, 始终 idle, 信任恒 0)")

    banner("一周记忆增长 (观察/反思) — 认知深化")
    for name, _, _, _ in NPCS:
        npc = w.npc(name)
        n_obs = len(npc.store.all_valid(types=["observation"]))
        n_refl = len(npc.store.all_valid(types=["reflection"]))
        n_self = len([r for r in npc.store.all_valid(types=["reflection"])
                      if r.player_id is None])
        print(f"   {name:<8} 观察{n_obs:>3} / 反思{n_refl:>3} (含自我反思{n_self})")
    print("\n   自我反思已触发 (阈值调到 25): 高频互动的 NPC 产生高阶自我认知,")
    print("   疏离的将军几乎无认知。记忆随时间降权 (遗忘), 但信任不淡化。")

    w.close()
    print(f"\n世界状态已存: {os.path.abspath(DATA)}/world.db  (每 NPC 独立 <name>.db)")
    print("可用 tools/inspect_npc.py data/sim/<name>.db 深入审查任一 NPC 的记忆流与证据链。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
