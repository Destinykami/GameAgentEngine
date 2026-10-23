#!/usr/bin/env python3
"""world_auto_sim.py — 多智能体自治世界 (旅行者也是 agent, 世界自己演)。

与 world_sim.py (脚本驱动旅行者) 不同: 这里所有实体都是 Agent, 各自
「感知 (非全知) → LLM 决策 → 行动」, 行动相互影响、影响世界。脚本只提供
初始世界 (区域/NPC/旅行者目标) 和时间推进, 不写任何角色的走位/台词/动作。

目标 (各 agent 的 goal 驱动, LLM 自己走): 旅行者想结束眼狩令, 将军要维护秩序。
  谁赢、怎么赢、要多久 —— 不由脚本规定, 由两者 (和城里其他人) 的交互涌现。

结局 (B+ 涌现, 未知):
  - 战斗结局: 旅行者把将军血条打空 → 眼狩令随将军倒台而废止 (引擎物理, 不变);
  - 说服结局: 旅行者向将军陈述证据, 是否被说服由 LLM 当场裁决 (看她的信念 +
    旅行者呈上的全部证据 + 本次往来), 无次数门槛 —— 可能一天就成, 也可能十天都不成。
  证据本身也由 LLM 从每次对话里生成 (对照已收集证据去重), 不是写死的槽位。

运行: .venv/bin/python examples/world_auto_sim.py   (真 LLM, 需 SGLang)
步频: 每天 8 个关键时刻 (07:00~21:00, 每 2 小时一步) × 10 天 = 80 步, 每步每个存活
  agent 一次决策 LLM + 感知/反思/对话。比脚本世界贵, 但世界自己演。
"""
from __future__ import annotations

import json
import os
import shutil


from game_agent import (RealLLM, World, Location, make_embedder)

DATA = os.path.join(os.path.dirname(__file__), "..", "data", "auto_sim")
# 直播文件: 每跑完一步就 append 一行 (meta/step/done), 供前端 ?live 模式轮询实时跟随。
# 与最终 timeline.json 并存 (timeline.json 仍为跑完后的离线回放源)。
LIVE_JSONL = os.path.join(os.path.dirname(__file__), "..", "visualization", "public", "live.jsonl")
REFLECT_THRESHOLD = 50.0     # 每 2h 一步后交互量约为稀疏步的 2.7 倍, 阈值相应抬高,
                             # 让自我反思的总频率 (和额外 LLM 调用) 大致不变
# B+ 涌现: 不再有脚本层门控 (REASON_NEEDED/ATTACK_NEEDED/PERSUADE_N/ONE_PERSUADE_PER_DAY
# 全删)。理由由 LLM 从对话里生成 (涌现), 将军是否被说服由 LLM 当场裁决 —— 结局未知。
# 只保留一个"证据容量"上限 (防旅行者记忆无限膨胀, 不是通关门槛)。
REASON_CAP = 6               # 旅行者最多持多少条证据 (容量, 非门槛)
DAYS = 10                    # 模拟天数 (结局由 agent 交互涌现, 可能提前收束也可能不收束)
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
     "shogun", "坐镇神樱庭, 你是稻妻统治者, 极固执、重秩序、视眼狩令为稻妻根基。来劝的多是空口白话, "
     "你迄今没见到足以撼动你的实证。是否被说服而废止眼狩令, 由你自己权衡判断: 空话动摇不了你, "
     "但若切实的实证一再打动你, 你也会重新考量。留驻神樱庭, 击退来犯者。"),
]
TRAVELER_GOAL = ("你想劝雷电将军废止眼狩令, 但她极固执重秩序, 空口白话根本不听。怎么打动她由你定策略:\n"
                 "城里每个人都在眼狩令下有各自的苦 —— 医者桃音 (持眼, 救助伤者)、学者小梅 (持眼, 典籍载有眼狩令之弊)、"
                 "铁匠刚郎 (生意受损)。找他们谈 (talk)、帮持眼者藏匿 (help)、在城里留意并目击执行官收缴神之眼的暴行, "
                 "都能让你拿到她需要的实证。你也可以找刚郎 talk 锻武器变强 (攻会提升), 既是自卫也是底气 —— "
                 "但变强不等于她就会听, 关键还是拿什么说服她。把这些证据攒起来, 再去神樱庭当面向她陈述, "
                 "能否废止全看你的陈述和证据够不够打动她。前期先取证、别急着空手去劝; "
                 "到神樱庭后留驻别走, 若执行官来扰应付但别离开。")


def banner(text: str) -> None:
    print(f"\n{'═' * 70}\n{text}\n{'═' * 70}")


def status_line(w: World) -> str:
    """每个存活 agent 的血/位置; 旅行者额外显示已收集证据数/攻 (涌现, 无门槛)。"""
    parts = []
    for name, e in w.entities.items():
        if e.is_alive():
            base = f"{name}血{e.health}@{e.location.name}"
            if e.kind == "player":
                base += f"(证据{len(e.reasons)}条,攻{e.attack})"
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
# 持眼者是否算目击。全部经 World 的动作效果钩子注入 —— 引擎(game_agent)保持
# 通用 (只出动作空间+物理规则), 不硬编码任何稻妻细节。本层可被别的"世界"替换。
WEAPON_GAIN = 3    # 与铁匠对话一次, 攻 +N (步频加密后从 4 调到 3, 保前期弧线)
WEAPON_CAP = 24    # 攻的上限


def _generate_reason(world, agent, target, utterance: str, reply: str) -> str | None:
    """B+ 涌现: 让 LLM 从这次对话里提炼一条关于眼狩令之弊的"新证据"。

    新颖性对照: 把已收集的证据喂进去, 要求 LLM 只给"没见过"的; 确无新证据则回 NONE
    (不硬凑)。去重双保险: LLM 新颖性判断是语义去重, add_reason 的文本去重是兜底。
    无 LLM / 调用失败 → None (不强行生成)。证据文本从此是活的, 不再是写死的槽位。
    """
    llm = world._agent_llms.get(agent.name)
    if llm is None or not hasattr(llm, "ask"):
        return None
    known = " / ".join(agent.reasons) if agent.reasons else "尚无"
    prompt = (
        f"旅行者与{target.name} (角色: {target.role or '百姓'}) 交谈。\n"
        f"旅行者说: {utterance}\n{target.name}答: {reply}\n"
        f"旅行者已收集的证据: {known}\n"
        "任务: 从这段对话中提炼旅行者新得到的、关于眼狩令之弊的一条'新证据/看法', "
        "且必须不在已收集证据里。确无新证据就输出 NONE; 否则用一句第三人称概括 "
        "(不要照抄对话原文)。"
    )
    try:
        raw = llm.ask(prompt, system="你在提炼证据, 只输出一句概括, 或 NONE。",
                      max_tokens=80).strip()
    except Exception:
        return None
    if not raw or raw.upper() == "NONE" or raw.startswith("无"):
        return None
    return raw


def inazuma_talk_effect(world, agent, target, action, ve) -> None:
    # 证据 (仅玩家积累): LLM 从这次对话生成 (涌现), 对照已收集证据做新颖性去重
    if agent.kind == "player":
        r = _generate_reason(world, agent, target, action.get("utterance", ""), ve.reply)
        if r and agent.add_reason(r, world.reason_cap):
            ve.reason_added = r
            ve.reason_count = len(agent.reasons)
        elif r:
            # 去重反馈: 证据重复不新增, 写入行动者历史让 LLM 看得见 "这条没算数",
            # 别把同一来源问到底 (静默丢弃会让 LLM 误以为已积累、原地反复对话)。
            agent.record(f"向 {target.name} 取的证据重复, 未新增 (现{len(agent.reasons)}条)")
    # 铁匠: 对话 = 锻一把武器, 攻提升 (与证据独立, 找铁匠既取证又锻刀)
    if "blacksmith" in target.role and agent.attack < WEAPON_CAP:
        agent.attack = min(WEAPON_CAP, agent.attack + WEAPON_GAIN)
        ve.weapon_attack = agent.attack


def _parse_json_obj(raw: str) -> dict | None:
    """从模型输出里抠出 JSON 对象 (容忍 markdown 代码围栏与前后杂字); 失败返 None。"""
    t = raw.strip()
    if t.startswith("```"):
        parts = t.split("```")
        t = parts[1] if len(parts) > 1 else t
        if t.startswith("json"):
            t = t[4:]
        t = t.strip()
    s, e = t.find("{"), t.rfind("}")
    if s != -1 and e > s:
        try:
            return json.loads(t[s:e + 1])
        except Exception:
            return None
    return None


def _judge_shogun(llm, shogun, traveler, utterance: str, reply: str) -> tuple[bool, str]:
    """B+ 涌现: LLM 当场裁决将军是否被说服到废止眼狩令 (替代计数器)。

    依据 = 她的目标(信念) + 旅行者已呈上的全部证据(累积) + 本次对话往来。极固执、
    空口白话不动摇、需实证且被反复打动 —— 这些约束写进裁决提示, 由 LLM 综合判断。
    返回 (是否被说服, 裁决依据)。无 LLM / 解析失败 → (False, ...) 保守不误判。
    """
    if llm is None or not hasattr(llm, "ask"):
        return False, ""
    evidence = " / ".join(traveler.reasons) if traveler.reasons else "尚未呈上任何证据"
    prompt = (
        f"你裁决雷电将军是否已被说服到废止眼狩令。\n"
        f"她的目标/信念: {shogun.goal}\n"
        f"旅行者已呈上的证据(累积): {evidence}\n"
        f"本次对话旅行者说: {utterance}\n将军答: {reply}\n"
        "综合以上, 她现在是否被充分打动而愿意废止眼狩令? 她极固执重秩序, "
        "空口白话动摇不了她, 需切实的实证且被反复打动才肯。"
        '输出严格 JSON: {"revoked": true|false, "reason": "一句话依据"}'
    )
    try:
        raw = llm.ask(prompt, system="你是将军心志的裁决者, 只输出 JSON。",
                      max_tokens=200)
    except Exception:
        return False, ""
    data = _parse_json_obj(raw)
    if not data:
        return False, ""
    return bool(data.get("revoked", False)), str(data.get("reason", ""))


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
    # 证据容量 (引擎通用容量, 非门槛): 限制旅行者持有证据条数, 防记忆无限膨胀。
    w.reason_cap = REASON_CAP
    register_scenario(w)   # 注入稻妻情境的动作效果 (证据生成/锻刀/目击)
    llm = RealLLM()
    emb = make_embedder()

    for name, traits, loc, hp, atk, dfn, role, goal in NPCS:
        w.add_npc(name, traits, llm=llm, embedder=emb, data_dir=DATA,
                  location=loc, reflection_threshold=REFLECT_THRESHOLD,
                  autonomous=True)
        e = w.get(name)
        e.health, e.attack, e.defense, e.goal, e.role = hp, atk, dfn, goal, role
    w.add_agent_player("旅行者", "稻妻主城", TRAVELER_GOAL, llm=llm,
                       persona_traits={"social": 0.5, "goal_oriented": 0.9},
                       health=380, attack=12, defense=5)   # 血 300→380: 每 2h 一步后执行官持续追击的消耗翻倍,
                                     # 380 可撑完全程 (约 9 天满追击), 仍要应付搜捕

    # 开场世界事件: 眼狩令生效
    w.world_event("雷电将军颁布眼狩令: 全城神之眼一律收缴", now=7.0)
    banner("世界已建, 所有 agent 有各自目标。旅行者目标: " + TRAVELER_GOAL)
    print("初始:", status_line(w))

    shogun = w.get("雷电将军")
    decree_ended = False
    timeline: list[dict] = []   # 结构化时间线 (供回放)

    # 直播增量写: 先写 meta 行 (前端用它建 timeline 元数据), 之后每步 append 一行,
    # 结尾写 done 行。前端 ?live 轮询此文件实时跟随 (见 visualization ?live 模式)。
    live_f = open(LIVE_JSONL, "w", encoding="utf-8")
    live_f.write(json.dumps({"__meta__": True, "schema_version": 1,
                             "world": {"name": w.name, "coordinate_system": "location-name",
                                       "render_map": "inazuma-v1"},
                             "reason_needed": None, "attack_needed": None,
                             "persuade_n": None}, ensure_ascii=False) + "\n")
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
                    # B+ 涌现: 将军是否被说服由 LLM 当场裁决 (她的信念+已呈证据+本次往来),
                    # 无计数器。裁决驳回时回喂旅行者历史, 让它知道"现在劝没成、该去积累
                    # 更多证据", 避免原地反复劝 (与旧双关同样的防卡死回喂)。
                    reply = next((ve.reply for ve in w.visual_events
                                  if ve.type == "conversation" and ve.actor == "旅行者"
                                  and ve.target == "雷电将军"), "")
                    revoked, why = _judge_shogun(llm, shogun, trav,
                                                 t_act.get("utterance", ""), reply)
                    if revoked:
                        w.world_event("雷电将军被旅行者说服, 废止眼狩令: 持眼者可保留神之眼",
                                      now=now)
                        note = f"★ 雷电将军被说服 ({why}), 废止眼狩令!"
                        print(f"   {note}")
                        decree_ended = True
                    else:
                        note = f"(将军尚未被说服: {why})" if why else "(将军尚未被说服)"
                        print("   " + note)
                        trav.record("将军尚未被说服: 证据还不够打动她, "
                                    "去城里向更多人取证/目击暴行, 积累更多实证再来劝")
            # 结构化视觉事件 (引擎单一事实源): 本步 execute_action 的事件 +
            # 结局 world_event (若本步触发)。前端回放读它, 不解析中文 events 串。
            visual = [ve.to_dict() for ve in w.visual_events]
            w.visual_events.clear()
            step = {"day": day, "moment": moment, "clock": now,
                    "events": events, "visual_events": visual,
                    "note": note, "states": snapshot(w),
                    "persuade": None, "decree_ended": decree_ended,
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
        print(f"\n   {DAYS} 天结束, 眼狩令仍在 (旅程未让将军废止)。将军: 血{shogun.health}, "
              f"旅行者证据 {len(w.get('旅行者').reasons)} 条。")
    # 存时间线 (供 replay.py 回放)
    tl_path = os.path.join(DATA, "timeline.json")
    with open(tl_path, "w", encoding="utf-8") as f:
        # 顶层保留旧键 (reason_needed/attack_needed/persuade_n) 兼容 replay.py, B+ 下为 null
        # (涌现, 无门控); schema_version + world 供前端 (见 VisualizationPlan §6 数据契约)。
        # 每个 step 的 visual_events 是结构化事实源, events 串为派生兼容产物。
        json.dump({"schema_version": 1,
                   "world": {"name": w.name, "coordinate_system": "location-name",
                             "render_map": "inazuma-v1"},
                   "reason_needed": None, "attack_needed": None,
                   "persuade_n": None, "steps": timeline}, f, ensure_ascii=False,
                  indent=2)
    w.close()
    print(f"\n世界状态已存: {os.path.abspath(DATA)}/world.db")
    print(f"时间线已存:   {tl_path}  (回放: .venv/bin/python examples/replay.py)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
