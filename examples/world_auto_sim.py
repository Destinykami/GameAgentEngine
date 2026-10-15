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
步频: 每天 8 个关键时刻 (07:00~21:00, 每 2 小时一步) × 10 天 = 80 步, 每步每个存活
  agent 一次决策 LLM + 感知/反思/对话。比脚本世界贵, 但世界自己演。
"""
from __future__ import annotations

import json
import os
import shutil
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from persona_agent import (RealLLM, World, Location, make_embedder)

DATA = os.path.join(os.path.dirname(__file__), "..", "data", "auto_sim")
# 直播文件: 每跑完一步就 append 一行 (meta/step/done), 供前端 ?live 模式轮询实时跟随。
# 与最终 timeline.json 并存 (timeline.json 仍为跑完后的离线回放源)。
LIVE_JSONL = os.path.join(os.path.dirname(__file__), "..", "visualization", "public", "live.jsonl")
REFLECT_THRESHOLD = 50.0     # 每 2h 一步后交互量约为稀疏步的 2.7 倍, 阈值相应抬高,
                             # 让自我反思的总频率 (和额外 LLM 调用) 大致不变
PERSUADE_N = 5               # 双关都过之后, 还需当面劝说多少次 → 被说服 (眼狩令废止)
ONE_PERSUADE_PER_DAY = True  # 将军听完"需要时间考虑", 当天再劝无效
REASON_NEEDED = 4            # 双关①: 旅行者需积累多少条反眼狩令的理由 (帮持眼者/取证, 来源需分散)
ATTACK_NEEDED = 20           # 双关②: 旅行者攻击力需达到多少, 将军才肯正眼看
DAYS = 10                    # 模拟天数 (准备 2-3 天 + 劝说 5 天, 留够空间)
STEPS_PER_DAY = 8            # 每天关键时刻数 (每 2 小时一步)
MOMENTS = [7.0, 9.0, 11.0, 13.0, 15.0, 17.0, 19.0, 21.0]   # 每 2 小时 (07:00~21:00, 保留 09/19 锚点)

LOCATIONS = [
    Location("稻妻主城", 0, 0),
    Location("治疗堂", 1, 0),
    Location("锻造坊", 2, 0),
    Location("眼狩署", 0, 1),
    Location("神樱庭", 0, 3),
    Location("城外官道", 5, 5),
]

# (名字, 人格, 位置, 血量, 攻, 防, 角色, 目标)
NPCS = [
    ("桃音",   {"social": 0.8, "goal_oriented": 0.3}, "治疗堂", 80, 8, 2,
     "vision_holder,healer", "护住雷神之眼, 在眼狩令下活下来, 救助伤者 (见过许多持眼者的苦)"),
    ("刚郎",   {"social": 0.3, "goal_oriented": 0.8}, "锻造坊", 100, 12, 4,
     "blacksmith", "打造武器谋生, 把货卖给可信的买家; 对可信者锻造更利的武器"),
    ("小梅",   {"social": 0.6, "goal_oriented": 0.5}, "稻妻主城", 70, 6, 1,
     "scholar,vision_holder", "护住风神之眼, 保存孤本典籍, 与可信之人互通情报 (典籍载有眼狩令之弊)"),
    ("执行官", {"social": 0.2, "goal_oriented": 0.7}, "眼狩署", 120, 10, 8,   # 攻 18→10: 每 2h 一步后搜捕机会多 2.7 倍, 不削攻旅行者会在
                                      # 劝说弧线中途 (第5-6天) 被磨死; 10 攻下每击 3-7 伤, 全程追而不杀
     "enforcer", "执行眼狩令, 搜捕并制服持有神之眼的人, 见到持眼者就攻击"),
    ("雷电将军", {"social": 0.1, "goal_oriented": 0.9, "stubborn": 0.9}, "神樱庭", 300, 20, 15,
     "shogun", "坐镇神樱庭, 你是稻妻统治者, 极固执重秩序。空口劝说休想动你 —— "
     "来者须拿出实证 (眼狩令之弊) 且有实力 (攻不低于20), 你才肯听; 否则击退。"
     "即便听完也要'容我考虑', 非多次打动不可。留在神樱庭, 击退来犯者"),
]
TRAVELER_GOAL = ("劝雷电将军废止眼狩令, 但将军极固执 —— 空口白话她根本不听, 你得先做足功课:\n"
                 "① 积累理由 (至少4条, 将军要实证, 证据须来自不同人/不同事): 帮桃音藏好雷神之眼 (help桃音)、找小梅 "
                 "的孤本典籍中取证眼狩令之弊 (talk小梅)、找桃音谈眼狩令之弊取证言 (talk桃音)、在城里留意并目击执行官收缴神之眼的暴行 "
                 "(与她同处一地即可)。桃音+刚郎最多凑3条, 必须再找小梅取证或亲眼目击收缴 —— 够到4条再算齐。"
                  "同一理由只计一次: 重复找同一个人问同样的事不增加条数 (桃音最多给2条: 证言+帮藏匿, "
                  "刚郎1条, 小梅1条, 目击收缴1条), 凑不齐就去下一个来源。\n"
                 "② 提升实力 (攻到20): 找刚郎反复 talk 锻武器, 每次攻+3, 锻到够强将军才正眼看你。\n"
                 "两关都过后再去神樱庭当面劝说, 她听完仍要'容我考虑'、当天再劝无效, 需多日反复 "
                 "打动。前期先积累理由+锻武器, 别急着去劝; 到神樱庭后留驻别走, 若执行官来扰应付但别离开。")


def banner(text: str) -> None:
    print(f"\n{'═' * 70}\n{text}\n{'═' * 70}")


def status_line(w: World) -> str:
    """每个存活 agent 的血/位置; 旅行者额外显示理由数/攻 (双关进度)。"""
    parts = []
    for name, e in w.entities.items():
        if e.is_alive():
            base = f"{name}血{e.health}@{e.location.name}"
            if e.kind == "player":
                base += f"(理由{len(e.reasons)}/{REASON_NEEDED},攻{e.attack}/{ATTACK_NEEDED})"
            parts.append(base)
        else:
            parts.append(f"{name}✝")
    return " | ".join(parts)


def snapshot(w: World) -> dict:
    """抓一个世界状态快照 (供回放): 每个 agent 的血/位置/理由/攻/角色/存活。"""
    return {
        name: {"health": e.health, "loc": e.location.name, "dead": e.dead,
               "reasons": list(e.reasons), "attack": e.attack, "role": e.role,
               "kind": e.kind}
        for name, e in w.entities.items()
    }


# ===================================================================== 情境层
# 稻妻·眼狩令 的具体世界行为: 理由(证据)怎么产生、对话铁匠是否锻刀、执行官收缴
# 持眼者是否算目击。全部经 World 的动作效果钩子注入 —— 引擎(persona_agent)保持
# 通用 (只出动作空间+物理规则), 不硬编码任何稻妻细节。本层可被别的"世界"替换。
WEAPON_GAIN = 3    # 与铁匠对话一次, 攻 +N (步频加密后从 4 调到 3, 保前期弧线)
WEAPON_CAP = 24    # 攻的上限


def _reason_for_role(target) -> str | None:
    """固定理由映射 (本提交为行为保持; LLM 从对话生成理由的涌现改法见后续)。"""
    if "scholar" in target.role:
        return "从小梅的孤本典籍中取证: 眼狩令令持眼者流离失所"
    if "healer" in target.role:
        return "听桃音讲述眼狩令下持眼者被迫离散、伤者无依的苦"
    if "blacksmith" in target.role:
        return "刚郎作证: 眼狩令收缴神之眼后持眼者离散, 武器生意断绝, 铁匠营生受损"
    return None


def inazuma_talk_effect(world, agent, target, action, ve) -> None:
    # 理由 (仅玩家积累): 学者取证 / 医者证言 / 铁匠经济之弊
    if agent.kind == "player":
        r = _reason_for_role(target)
        if r and agent.add_reason(r, world.reason_cap):
            ve.reason_added = r
            ve.reason_count = len(agent.reasons)
        elif r:
            # 去重反馈: 同一条理由重复取得不新增, 写入行动者历史让 LLM 看得见,
            # 别把同一来源问到底 (静默丢弃会让 LLM 误以为已积累、原地反复对话)。
            agent.record(f"向 {target.name} 取的理由已重复, 未新增 (现{len(agent.reasons)}条)")
    # 铁匠: 对话 = 锻一把武器, 攻提升 (与理由独立, 找铁匠既取证又锻刀)
    if "blacksmith" in target.role and agent.attack < WEAPON_CAP:
        agent.attack = min(WEAPON_CAP, agent.attack + WEAPON_GAIN)
        ve.weapon_attack = agent.attack


def inazuma_attack_effect(world, agent, target, action, ve) -> None:
    # 执行官收缴持眼者 → 同地点的目击玩家积累一条理由 (亲眼所见)
    if "enforcer" in agent.role and "vision_holder" in target.role:
        for witness in world.entities.values():
            if (witness.kind == "player" and witness is not agent
                    and witness is not target and witness.is_alive()
                    and witness.location is target.location):
                if witness.add_reason(
                        f"目睹执行官当众收缴 {target.name} 的神之眼, 其家破人亡",
                        world.reason_cap):
                    ve.witnessed = True
                    ve.reason_count = len(witness.reasons)
                else:
                    witness.record(f"目睹收缴 {target.name} 的理由已重复, 未新增 "
                                   f"(现{len(witness.reasons)}条)")


def inazuma_help_effect(world, agent, target, action, ve) -> None:
    # 帮持眼者护住神之眼 = 一条反眼狩令的理由 (仅玩家, 仅 help 动作)
    if action.get("action") == "help" and agent.kind == "player" \
            and "vision_holder" in target.role:
        r = f"助 {target.name} 藏好神之眼, 令其免遭收缴"
        if agent.add_reason(r, world.reason_cap):
            ve.reason_added = r
            ve.reason_count = len(agent.reasons)
        else:
            agent.record(f"帮 {target.name} 藏匿的理由已重复, 未新增 "
                         f"(现{len(agent.reasons)}条)")


def register_scenario(world) -> None:
    """把稻妻情境的动作效果注册进引擎 (引擎与世界行为解耦的注入点)。"""
    world.add_action_effect("talk", inazuma_talk_effect)
    world.add_action_effect("attack", inazuma_attack_effect)
    world.add_action_effect("help", inazuma_help_effect)
    world.add_action_effect("hide", inazuma_help_effect)


def main() -> int:
    shutil.rmtree(DATA, ignore_errors=True)
    os.makedirs(DATA, exist_ok=True)
    w = World("稻妻城", LOCATIONS, path=os.path.join(DATA, "world.db"))
    # 理由上限 (引擎通用容量): 抬到 REASON_NEEDED。前 3 条最容易 (桃音证言+帮桃音藏匿+
    # 刚郎证言), 第 4 条必须来自小梅(典籍取证/帮藏匿)或目击执行官收缴 —— 逼旅行者满城跑。
    w.reason_cap = REASON_NEEDED
    register_scenario(w)   # 注入稻妻情境的动作效果 (理由/锻刀/目击)
    llm = RealLLM()
    emb = make_embedder()

    for name, traits, loc, hp, atk, dfn, role, goal in NPCS:
        npc = w.add_npc(name, traits, llm=llm, embedder=emb, data_dir=DATA,
                        location=loc, reflection_threshold=REFLECT_THRESHOLD)
        e = w.get(name)
        e.health, e.attack, e.defense, e.goal, e.role = hp, atk, dfn, goal, role
        w._agent_llms[name] = llm
        w._agent_personas[name] = traits
    w.add_agent_player("旅行者", "稻妻主城", TRAVELER_GOAL, llm=llm,
                       persona_traits={"social": 0.5, "goal_oriented": 0.9},
                       health=380, attack=12, defense=5)   # 血 300→380: 每 2h 一步后执行官持续追击的消耗翻倍,
                                     # 380 可撑完全程 (约 9 天满追击), 仍要应付搜捕

    # 开场世界事件: 眼狩令生效
    w.world_event("雷电将军颁布眼狩令: 全城神之眼一律收缴", now=7.0)
    banner("世界已建, 所有 agent 有各自目标。旅行者目标: " + TRAVELER_GOAL)
    print("初始:", status_line(w))

    shogun = w.get("雷电将军")
    persuade_count = 0
    decree_ended = False
    last_persuade_day = -1   # 上次有效劝说的天 (将军"容我考虑", 当天再劝无效)
    timeline: list[dict] = []   # 结构化时间线 (供回放)

    # 直播增量写: 先写 meta 行 (前端用它建 timeline 元数据), 之后每步 append 一行,
    # 结尾写 done 行。前端 ?live 轮询此文件实时跟随 (见 visualization ?live 模式)。
    live_f = open(LIVE_JSONL, "w", encoding="utf-8")
    live_f.write(json.dumps({"__meta__": True, "schema_version": 1,
                             "world": {"name": w.name, "coordinate_system": "location-name",
                                       "render_map": "inazuma-v1"},
                             "reason_needed": REASON_NEEDED, "attack_needed": ATTACK_NEEDED,
                             "persuade_n": PERSUADE_N}, ensure_ascii=False) + "\n")
    live_f.flush()
    # 开场世界事件: 引擎已产出结构化 VisualEvent, 直接序列化 (不再硬编码字符串)。
    opening_ve = [ve.to_dict() for ve in w.visual_events]
    opening_events = [ve.describe() for ve in w.visual_events]
    w.visual_events.clear()
    opening = {"day": 0, "moment": 7.0, "clock": 7.0,
               "events": opening_events, "visual_events": opening_ve,
               "states": snapshot(w), "persuade": 0, "decree_ended": False,
               "shogun_dead": False}
    timeline.append(opening)
    live_f.write(json.dumps(opening, ensure_ascii=False) + "\n"); live_f.flush()

    for day in range(1, DAYS + 1):
        for moment in MOMENTS:
            now = (day - 1) * 24.0 + moment
            banner(f"第 {day} 天 {moment:02.0f}:00  (所有 agent 自治)")
            events, decisions = w.step_autonomous(now)
            for ev in events:
                print("   " + ev)
            print("   [状态] " + status_line(w))
            note = ""
            # 结局判定: 将军阵亡 或 被说服 (旅行者本步对将军直接 talk 才计数)
            if shogun.dead:
                note = "★ 雷电将军阵亡! 眼狩令随将军倒台而废止。"
                print(f"   {note}")
                decree_ended = True
            else:
                t_act = decisions.get("旅行者", {})
                if t_act.get("action") == "talk" and t_act.get("target") == "雷电将军":
                    trav = w.get("旅行者")
                    # 双关: 理由不够 或 实力不够 → 将军驳回 (空口白话无效)。
                    # 驳回必须回喂旅行者历史 (trav.record): 只打印不进决策的话, LLM 看不见
                    # "现在劝没用", 会在神樱庭原地反复劝 (理由永远差 1 条的僵局)。
                    if len(trav.reasons) < REASON_NEEDED:
                        note = (f"雷电将军驳回: '你既无实证, 一派胡言。' "
                                f"[理由{len(trav.reasons)}/{REASON_NEEDED} 不足]")
                        momone = w.get("桃音")
                        momone_loc = f", 她现在在{momone.location.name}" if momone and not momone.dead else ""
                        xiaomei = w.get("小梅")
                        xiaomei_loc = f", 她现在在{xiaomei.location.name}" if xiaomei and not xiaomei.dead else ""
                        trav.record(f"将军驳回劝说: 理由{len(trav.reasons)}/{REASON_NEEDED}不足, "
                                    f"先去凑齐 (帮桃音藏匿 help桃音{momone_loc} / "
                                    f"找小梅取证 talk小梅{xiaomei_loc} / 目击执行官收缴), "
                                    f"别在神樱庭原地再劝")
                    elif trav.attack < ATTACK_NEEDED:
                        note = (f"雷电将军驳回: '就凭你这副身板也敢诘问本将军?' "
                                f"[攻{trav.attack}/{ATTACK_NEEDED} 不足]")
                        trav.record(f"将军驳回劝说: 攻{trav.attack}/{ATTACK_NEEDED}不足, "
                                    f"先找刚郎 talk 锻武器, 别在神樱庭原地再劝")
                    elif ONE_PERSUADE_PER_DAY and day == last_persuade_day:
                        note = "雷电将军: '本将军今日已听过了, 容我再想想。' 当天再劝无效"
                        trav.record("将军今日已听过劝说, 当天再劝无效, 留驻等明天再劝")
                    else:
                        persuade_count += 1
                        last_persuade_day = day
                        note = (f"双关已过, 旅行者当面劝说, 将军沉吟'容我考虑' "
                                f"— {persuade_count}/{PERSUADE_N}")
                    print("   (" + note + ")")
                if persuade_count >= PERSUADE_N and not shogun.dead:
                    w.world_event("雷电将军被旅行者说服, 废止眼狩令: 持眼者可保留神之眼",
                                  now=now)
                    note = f"★ 雷电将军被说服 (当面劝说 {persuade_count} 次), 废止眼狩令!"
                    print(f"   {note}")
                    decree_ended = True
            # 结构化视觉事件 (引擎单一事实源): 本步 execute_action 的事件 +
            # 结局 world_event (若本步触发)。前端回放读它, 不解析中文 events 串。
            visual = [ve.to_dict() for ve in w.visual_events]
            w.visual_events.clear()
            step = {"day": day, "moment": moment, "clock": now,
                    "events": events, "visual_events": visual,
                    "note": note, "states": snapshot(w),
                    "persuade": persuade_count, "decree_ended": decree_ended,
                    "shogun_dead": shogun.dead}
            timeline.append(step)
            live_f.write(json.dumps(step, ensure_ascii=False) + "\n"); live_f.flush()
            if decree_ended or shogun.dead:
                break
        if decree_ended or shogun.dead:
            break

    # 直播 done 行: 前端 ?live 收到后停止轮询, 切回普通回放 (可往回拖)。
    live_f.write(json.dumps({"__done__": True, "decree_ended": decree_ended,
                             "shogun_dead": shogun.dead}, ensure_ascii=False) + "\n")
    live_f.flush(); live_f.close()

    banner("结局")
    print(status_line(w))
    if decree_ended:
        print(f"\n   眼狩令已废止 (将军{'阵亡' if shogun.dead else '被说服'})。旅行者目标达成。")
    else:
        print(f"\n   {DAYS} 天结束, 眼狩令仍在。将军: 血{shogun.health}, 被劝说 {persuade_count}/{PERSUADE_N} 次。")
    # 存时间线 (供 replay.py 回放)
    tl_path = os.path.join(DATA, "timeline.json")
    with open(tl_path, "w", encoding="utf-8") as f:
        # 顶层保留旧键 (reason_needed/attack_needed/persuade_n) 兼容 replay.py;
        # 新增 schema_version + world 供前端 (见 VisualizationPlan §6 数据契约)。
        # 每个 step 的 visual_events 是结构化事实源, events 串为派生兼容产物。
        json.dump({"schema_version": 1,
                   "world": {"name": w.name, "coordinate_system": "location-name",
                             "render_map": "inazuma-v1"},
                   "reason_needed": REASON_NEEDED, "attack_needed": ATTACK_NEEDED,
                   "persuade_n": PERSUADE_N, "steps": timeline}, f, ensure_ascii=False,
                  indent=2)
    w.close()
    print(f"\n世界状态已存: {os.path.abspath(DATA)}/world.db")
    print(f"时间线已存:   {tl_path}  (回放: .venv/bin/python examples/replay.py)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
