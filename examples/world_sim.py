"""world_sim: 稻妻城·眼狩令 —— 世界监视器 (跑一段时间, 看每个 agent 的表现与世界演化)。

持续模拟: 旅行者跨两天穿行城中, 与每个 NPC 互动 (帮持眼者藏匿 / 务实交易 / 与执行官
周旋), 世界事件 (眼狩令生效 / 执行官搜捕) 持续发生。**每个 NPC 都会和旅行者对话**
(触发关系反思), 展示"每个 agent 在做什么、在想什么"。雷电将军保持疏离——旅行者从不
接近, 将军始终 idle, 对旅行者无任何关系认知 (信任恒 0), 形成对照。

每隔一天输出每个 NPC 的**状态快照** —— 档位、对旅行者的信任、记忆条数 (观察/反思/
计划)、最新的自我反思与关系反思 —— 展示 agent 认知表现。最后打印**信任演化轨迹**
与**世界变化** (记忆增长、档位变迁)。全程真实 LLM。

世界状态存 data/sim/world.db, 每 NPC 独立 data/sim/<name>.db。
跑法: python examples/world_sim.py   (需 LLM 可达, 约几分钟)
"""

from __future__ import annotations

import os
import shutil
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from persona_agent import World, Location, RealLLM, make_embedder

DATA = os.path.join(os.path.dirname(__file__), "..", "data", "sim")

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


def say(npc_name: str, line: str, reply: str) -> None:
    print(f"   {line}\n   {npc_name}: {reply}")


def snapshot(w: World, day_label: str) -> None:
    """输出每个 NPC 的状态快照: 档位 / 信任 / 记忆条数 / 最新反思。"""
    sub(f"{day_label} — 每个 NPC 的认知表现")
    for name, _, _, role in NPCS:
        npc = w.npc(name)
        loc = w.entities[name].location.name
        trust = npc.trust_toward("旅行者")
        n_obs = len(npc.store.all_valid(types=["observation"]))
        refl = npc.store.all_valid(types=["reflection"])
        n_refl = len(refl)
        n_plan = len(npc.store.all_valid(types=["plan"]))
        self_refl = [r.content for r in refl if r.player_id is None]
        rel_refl = [r.content for r in refl if r.player_id == "旅行者"]
        last_self = self_refl[-1] if self_refl else "· (尚未累积到自我反思阈值)"
        last_rel = rel_refl[-1] if rel_refl else "· (旅行者尚未与之建立关系认知)"
        print(f"\n[{loc}] {name} ({role})")
        print(f"   档位={npc._tier:<11} 信任→旅行者={trust:+.2f}   "
              f"记忆: 观察{n_obs} / 反思{n_refl} / 计划{n_plan}")
        print(f"   自我反思: {last_self}")
        print(f"   对旅行者的关系反思: {last_rel}")


def trust_row(w: World) -> dict:
    return {name: w.npc(name).trust_toward("旅行者") for name, _, _, _ in NPCS}


def main() -> int:
    shutil.rmtree(DATA, ignore_errors=True)
    os.makedirs(DATA, exist_ok=True)
    llm = RealLLM()
    emb = make_embedder()
    w = World("稻妻城", LOCATIONS, path=os.path.join(DATA, "world.db"))
    for name, persona, loc, _ in NPCS:
        w.add_npc(name, persona, llm=llm, embedder=emb, data_dir=DATA, location=loc)
    w.add_player("旅行者", "稻妻主城")

    # ------------------------------ 第一天 ------------------------------
    banner("第一天 07:00  眼狩令生效 (全图事件, 所有 NPC 感知)")
    w.world_event("雷电将军颁布眼狩令: 全城神之眼一律收缴", now=7.0)
    s = w.step(7.0)
    print("档位:", tiers_str(s["tiers"]))
    for name, _, _, _ in NPCS:   # 各 NPC 规划当天 (自我层: 各自在做什么)
        w.npc(name).generate_daily_plan(previous_day="", date="第1天", now=7.5)

    banner("第一天 09:00  旅行者到治疗堂, 帮桃音藏起雷神之眼")
    w.move("旅行者", "治疗堂", now=9.0)
    w.npc("桃音").observe("旅行者帮 桃音 把雷神之眼藏进了地窖", 9.0, player_id="旅行者")
    w.step(9.0)
    say("桃音", "桃音: 藏起神之眼, 他们会不会发现?",
        w.npc("桃音").speak("旅行者", "藏起神之眼, 他们会不会发现?", 9.5))

    banner("第一天 11:00  旅行者到锻造坊, 与刚郎谈务实委托")
    w.move("旅行者", "锻造坊", now=11.0)
    w.npc("刚郎").observe("旅行者 找 刚郎 委托打造武器, 言谈务实, 公平交易", 11.0,
                          player_id="旅行者")
    w.step(11.0)
    say("刚郎", "刚郎: 你这委托, 工期和报酬怎么算?",
        w.npc("刚郎").speak("旅行者", "你这委托, 工期和报酬怎么算?", 11.5))

    banner("第一天 14:00  旅行者回主城, 小梅打听眼狩令")
    w.move("旅行者", "稻妻主城", now=14.0)
    w.step(14.0)
    say("小梅", "小梅: 你怎么看眼狩令? 大家的神之眼都被收走了。",
        w.npc("小梅").speak("旅行者", "你怎么看眼狩令? 大家的神之眼都被收走了。", 14.0))

    banner("第一天 17:00  旅行者到眼狩署, 执行官盘问他是否私藏神之眼")
    w.move("旅行者", "眼狩署", now=17.0)
    w.npc("执行官").observe("旅行者 被目击帮助 桃音 藏匿神之眼", 17.0, player_id="旅行者")
    w.step(17.0)
    say("执行官", "执行官: 有人看到你往治疗堂跑, 说你在帮人藏神之眼。如实交代。",
        w.npc("执行官").speak("旅行者", "有人看到你往治疗堂跑, 说你在帮人藏神之眼。如实交代。", 17.5))

    banner("第一天 20:00  旅行者离开稻妻城 (距离调度: 全员降档)")
    w.move("旅行者", "城外官道", now=20.0)
    s = w.step(20.0)
    print("档位:", tiers_str(s["tiers"]), "(旅行者远离全城 → 全员 idle)")
    trust_row_1 = trust_row(w)
    snapshot(w, "第一天结束 (20:00)")

    # ------------------------------ 第二天 ------------------------------
    banner("第二天 08:00  旅行者回到稻妻主城, 各 NPC 规划新的一天")
    w.move("旅行者", "稻妻主城", now=32.0)
    w.step(32.0)
    for name, _, _, _ in NPCS:
        w.npc(name).generate_daily_plan(previous_day="第1天", date="第2天", now=32.5)

    banner("第二天 10:00  旅行者再到治疗堂, 更谨慎地帮桃音")
    w.move("旅行者", "治疗堂", now=34.0)
    w.npc("桃音").observe("旅行者 再次帮 桃音 转移雷神之眼, 这次藏得更隐蔽", 34.0,
                          player_id="旅行者")
    w.step(34.0)
    say("桃音", "桃音: 这样下去, 带着神之眼还能安心生活吗?",
        w.npc("桃音").speak("旅行者", "这样下去, 带着神之眼还能安心生活吗?", 34.5))

    banner("第二天 13:00  世界事件: 执行官搜捕全城神之眼 (眼狩署半径事件)")
    w.world_event("执行官带队搜捕全城的神之眼", now=37.0, at="眼狩署", radius=1.5)
    s = w.step(37.0)
    print("档位:", tiers_str(s["tiers"]))

    banner("第二天 15:00  旅行者到锻造坊, 刚郎欣赏其务实, 交易更热络")
    w.move("旅行者", "锻造坊", now=39.0)
    w.npc("刚郎").observe("刚郎 欣赏 旅行者 的务实, 主动多送了他一份材料", 39.0,
                          player_id="旅行者")
    w.step(39.0)
    say("刚郎", "刚郎: 上次那批货你用着如何? 这次给你加急。",
        w.npc("刚郎").speak("旅行者", "上次那批货你用着如何? 这次给你加急。", 39.5))

    banner("第二天 17:00  旅行者到眼狩署, 执行官因搜捕无果而迁怒")
    w.move("旅行者", "眼狩署", now=41.0)
    w.npc("执行官").observe("执行官 搜捕无果, 怀疑 旅行者 知情不报, 当面施压", 41.0,
                            player_id="旅行者")
    w.step(41.0)
    say("执行官", "执行官: 搜了三天一无所获, 城里谁在包庇, 你心里清楚。",
        w.npc("执行官").speak("旅行者", "搜了三天一无所获, 城里谁在包庇, 你心里清楚。", 41.5))

    banner("第二天 20:00  旅行者再次离开稻妻城")
    w.move("旅行者", "城外官道", now=44.0)
    s = w.step(44.0)
    print("档位:", tiers_str(s["tiers"]), "(旅行者远离全城 → 全员 idle)")
    trust_row_2 = trust_row(w)
    snapshot(w, "第二天结束 (20:00)")

    banner("世界演化: 旅行者对每个 NPC 的信任轨迹 (千人千面)")
    print(f"   {'NPC':<8} {'第一天':>8} {'第二天':>8} {'变化':>8}")
    for name, _, _, role in NPCS:
        d1, d2 = trust_row_1[name], trust_row_2[name]
        print(f"   {name:<8} {d1:>+8.2f} {d2:>+8.2f} {d2 - d1:>+8.2f}")
    print("\n   桃音(受助)信任升温 / 刚郎(务实交易)信任上升 / 小梅(好奇→担忧) /")
    print("   执行官(藏匿+迁怒)警惕 / 雷电将军疏离 (旅行者从不接近, 始终 idle, 信任恒 0)")

    banner("世界演化: 各 NPC 记忆增长 (观察/反思/计划)")
    for name, _, _, _ in NPCS:
        npc = w.npc(name)
        print(f"   {name:<8} 观察{len(npc.store.all_valid(types=['observation'])):>2} / "
              f"反思{len(npc.store.all_valid(types=['reflection'])):>2} / "
              f"计划{len(npc.store.all_valid(types=['plan'])):>2}")

    w.close()
    print(f"\n世界状态已存: {os.path.abspath(DATA)}/world.db  (每 NPC 独立 <name>.db)")
    print("可用 tools/inspect_npc.py data/sim/<name>.db 深入审查任一 NPC 的记忆流与证据链。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
