#!/usr/bin/env python3
"""world_auto_sim.py — 多智能体自治世界 (旅行者也是 agent, 世界自己演)。

与 world_sim.py (脚本驱动旅行者) 不同: 这里所有实体都是 Agent, 各自
「感知 (非全知) → LLM 决策 → 行动」, 行动相互影响、影响世界。脚本只提供
初始世界 (区域/NPC/旅行者目标) 和时间推进, 不写任何角色的走位/台词/动作。

目标弧线 (由旅行者的 goal 驱动, LLM 自己走): 打败并说服雷电将军结束眼狩令。
  前期: 帮桃音藏眼 + 找刚郎锻武器 (变强)
  中期: 对抗执行官 (搜捕持眼者)
  后期: 挑战雷电将军 (战斗 + 劝说) → 将军阵亡或被说服 → 眼狩令废止

结局条件: 雷电将军阵亡 (血条打空) 或被说服 (旅行者对TA劝说 >= PERSUADE_N 次)
  → 触发世界事件 "雷电将军废止眼狩令"。

运行: .venv/bin/python examples/world_auto_sim.py   (真 LLM, 需 SGLang)
稀疏步: 每天 3 个关键时刻 (09:00/14:00/19:00) × 7 天 = 21 步, 每步每个存活
  agent 一次决策 LLM + 感知/反思/对话。比脚本世界贵, 但世界自己演。
"""
from __future__ import annotations

import os
import shutil
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from persona_agent import (RealLLM, World, Location, make_embedder)

DATA = os.path.join(os.path.dirname(__file__), "..", "data", "auto_sim")
REFLECT_THRESHOLD = 25.0     # 调低, 让稀疏步的事件量也能触发反思
PERSUADE_N = 5               # 旅行者当面劝说雷电将军多少次 → 被说服 (眼狩令废止)
ONE_PERSUADE_PER_DAY = True  # 将军听完"需要时间考虑", 当天再劝无效 → 至少 5 天才可能成功
DAYS = 7                     # 模拟天数
STEPS_PER_DAY = 3            # 每天关键时刻数 (稀疏步)
MOMENTS = [9.0, 14.0, 19.0]  # 每天的时刻 (09:00/14:00/19:00)

LOCATIONS = [
    Location("稻妻主城", 0, 0),
    Location("治疗堂", 1, 0),
    Location("锻造坊", 2, 0),
    Location("眼狩署", 0, 1),
    Location("神樱庭", 0, 3),
    Location("城外官道", 5, 5),
]

# (名字, 人格, 位置, 血量, 攻, 防, 目标)
NPCS = [
    ("桃音",   {"social": 0.8, "goal_oriented": 0.3}, "治疗堂", 80, 8, 2,
     "护住雷神之眼, 在眼狩令下活下来, 救助伤者"),
    ("刚郎",   {"social": 0.3, "goal_oriented": 0.8}, "锻造坊", 100, 12, 4,
     "打造武器谋生, 把货卖给可信的买家"),
    ("小梅",   {"social": 0.6, "goal_oriented": 0.5}, "稻妻主城", 70, 6, 1,
     "护住风神之眼, 保存孤本典籍, 与可信之人互通情报"),
    ("执行官", {"social": 0.2, "goal_oriented": 0.7}, "眼狩署", 120, 18, 8,
     "执行眼狩令, 搜捕并制服持有神之眼的人"),
    ("雷电将军", {"social": 0.1, "goal_oriented": 0.9}, "神樱庭", 250, 16, 12,
     "坐镇神樱庭维护眼狩令与稻妻秩序, 击退来犯者; 你是统治者, 留在神樱庭不要离开"),
]
TRAVELER_GOAL = ("去神樱庭质问并劝说雷电将军结束眼狩令。将军极其固执, 不是一两次"
                 "能说服的 —— 她会听完说'容我考虑', 当天你再劝也无效, 要隔天才再劝。"
                 "你的攻击破不了她的防御, 别 attack, 要日日夜夜反复 talk 劝她回心转意, "
                 "耐心多日争取。到神樱庭后留驻, 不要离开; 若执行官来扰, 应付但别走开。")


def banner(text: str) -> None:
    print(f"\n{'═' * 70}\n{text}\n{'═' * 70}")


def status_line(w: World) -> str:
    """每个存活 agent 的血/位置 (供打印)。"""
    parts = []
    for name, e in w.entities.items():
        if e.is_alive():
            parts.append(f"{name}血{e.health}@{e.location.name}")
        else:
            parts.append(f"{name}✝")
    return " | ".join(parts)


def main() -> int:
    shutil.rmtree(DATA, ignore_errors=True)
    os.makedirs(DATA, exist_ok=True)
    w = World("稻妻城", LOCATIONS, path=os.path.join(DATA, "world.db"))
    llm = RealLLM()
    emb = make_embedder()

    for name, traits, loc, hp, atk, dfn, goal in NPCS:
        npc = w.add_npc(name, traits, llm=llm, embedder=emb, data_dir=DATA,
                        location=loc, reflection_threshold=REFLECT_THRESHOLD)
        e = w.get(name)
        e.health, e.attack, e.defense, e.goal = hp, atk, dfn, goal
        w._agent_llms[name] = llm
        w._agent_personas[name] = traits
    w.add_agent_player("旅行者", "稻妻主城", TRAVELER_GOAL, llm=llm,
                       persona_traits={"social": 0.5, "goal_oriented": 0.9},
                       health=300, attack=12, defense=5)

    # 开场世界事件: 眼狩令生效
    w.world_event("雷电将军颁布眼狩令: 全城神之眼一律收缴", now=7.0)
    banner("世界已建, 所有 agent 有各自目标。旅行者目标: " + TRAVELER_GOAL)
    print("初始:", status_line(w))

    shogun = w.get("雷电将军")
    persuade_count = 0
    decree_ended = False
    last_persuade_day = -1   # 上次有效劝说的天 (将军"容我考虑", 当天再劝无效)

    for day in range(1, DAYS + 1):
        for moment in MOMENTS:
            now = (day - 1) * 24.0 + moment
            banner(f"第 {day} 天 {moment:02.0f}:00  (稀疏步, 所有 agent 自治)")
            events, decisions = w.step_autonomous(now)
            for ev in events:
                print("   " + ev)
            print("   [状态] " + status_line(w))
            # 结局判定: 将军阵亡 或 被说服 (旅行者本步对将军直接 talk 才计数)
            if shogun.dead:
                print(f"   ★ 雷电将军阵亡! 眼狩令随将军倒台而废止。")
                decree_ended = True
                break
            t_act = decisions.get("旅行者", {})
            if t_act.get("action") == "talk" and t_act.get("target") == "雷电将军":
                if ONE_PERSUADE_PER_DAY and day == last_persuade_day:
                    print("   (雷电将军: '本将军已听过了, 容我再想想。' 当天再劝无效)")
                else:
                    persuade_count += 1
                    last_persuade_day = day
                    print(f"   (旅行者当面劝说雷电将军, 将军沉吟'容我考虑' — {persuade_count}/{PERSUADE_N})")
            if persuade_count >= PERSUADE_N and not shogun.dead:
                w.world_event("雷电将军被旅行者说服, 废止眼狩令: 持眼者可保留神之眼",
                              now=now)
                print(f"   ★ 雷电将军被说服 (当面劝说 {persuade_count} 次), 废止眼狩令!")
                decree_ended = True
                break
        if decree_ended or shogun.dead:
            break

    banner("结局")
    print(status_line(w))
    if decree_ended:
        print(f"\n   眼狩令已废止 (将军{'阵亡' if shogun.dead else '被说服'})。旅行者目标达成。")
    else:
        print(f"\n   一周结束, 眼狩令仍在。将军: 血{shogun.health}, 被劝说 {persuade_count}/{PERSUADE_N} 次。")
    w.close()
    print(f"\n世界状态已存: {os.path.abspath(DATA)}/world.db")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
