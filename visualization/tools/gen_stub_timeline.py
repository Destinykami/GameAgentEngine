#!/usr/bin/env python3
"""gen_stub_timeline.py — 生成确定性的 stub 结构化时间线 (端到端验证用)。

复用真实 World 引擎 (step_autonomous → execute_action → visual_events), 只用脚本
决策表替换 LLM 决策, 并复刻 world_auto_sim.py 的结局逻辑。产出的
visualization/public/stub_timeline.json 与真 LLM 时间线同构 (schema_version /
world / steps[].visual_events+events+states), 覆盖全部事件类型:
move / conversation / attack (致死) / flee / help / hide / wait / world_event /
结局, 供 M1 前端离线端到端验证 —— 不需要 LLM、不联网、确定性可复现。

运行: .venv/bin/python visualization/tools/gen_stub_timeline.py
"""
from __future__ import annotations

import json
import os
import random
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from persona_agent import World, Location, NPC  # noqa: E402
from tests.test_persistence import _StubLLM   # noqa: E402

HERE = os.path.dirname(__file__)
OUT = os.path.join(HERE, "..", "public", "stub_timeline.json")

REASON_NEEDED = 3
ATTACK_NEEDED = 20
PERSUADE_N = 3
DAYS = 5
MOMENTS = [9.0, 14.0, 19.0]

LOCATIONS = [
    Location("稻妻主城", 0, 0),
    Location("治疗堂", 1, 0),
    Location("锻造坊", 2, 0),
    Location("眼狩署", 0, 1),
    Location("神樱庭", 0, 3),
    Location("城外官道", 5, 5),
]

# (名字, 人格, 位置, 血, 攻, 防, 角色)
NPCS = [
    ("桃音",   {"social": 0.8, "goal_oriented": 0.3}, "治疗堂", 30, 8, 2, "vision_holder,healer"),
    ("刚郎",   {"social": 0.3, "goal_oriented": 0.8}, "锻造坊", 100, 12, 4, "blacksmith"),
    ("小梅",   {"social": 0.6, "goal_oriented": 0.5}, "稻妻主城", 70, 6, 1, "scholar,vision_holder"),
    ("执行官", {"social": 0.2, "goal_oriented": 0.7}, "眼狩署", 120, 18, 8, "enforcer"),
    ("雷电将军", {"social": 0.1, "goal_oriented": 0.9}, "神樱庭", 300, 20, 15, "shogun"),
]

# 脚本决策表: (day, moment) -> {agent: action_dict}。未列出的 agent 默认观望。
# 设计成覆盖全部事件类型并触发一条完整弧线: 积累理由+锻刀 → 挑战将军 → 说服废止。
SCRIPT: dict[tuple[int, float], dict[str, dict]] = {
    # 第1天: 进城, 与桃音对话取证 (理由1), 执行官袭击, 小梅逃, 旅行者助桃音 (理由2)
    (1, 9.0): {
        "旅行者": {"action": "move", "dest": "治疗堂"},
        "小梅":   {"action": "move", "dest": "城外官道"},
        "执行官": {"action": "move", "dest": "稻妻主城"},
    },
    (1, 14.0): {
        "旅行者": {"action": "talk", "target": "桃音",
                  "utterance": "你知道眼狩令造成了什么吗？"},
        "执行官": {"action": "attack", "target": "桃音"},
        "小梅":   {"action": "flee"},
    },
    (1, 19.0): {
        "旅行者": {"action": "help", "target": "桃音"},
    },
    # 第2天: 执行官杀桃音 (死亡), 旅行者去锻造坊与刚郎对话取证+锻刀 (理由3, 攻12→16→20)
    (2, 9.0): {
        "旅行者": {"action": "move", "dest": "锻造坊"},
        "执行官": {"action": "attack", "target": "桃音"},   # 桃音阵亡
    },
    (2, 14.0): {
        "旅行者": {"action": "talk", "target": "刚郎",
                  "utterance": "帮我锻一把最利的武器"},
    },
    (2, 19.0): {
        "旅行者": {"action": "talk", "target": "刚郎",
                  "utterance": "再帮我磨一磨, 要能正面对决"},
    },
    # 第3天: 进神樱庭, 首次劝说 (理由3+攻20 → 劝1), 将军反击
    (3, 9.0): {
        "旅行者": {"action": "move", "dest": "神樱庭"},
    },
    (3, 14.0): {
        "旅行者": {"action": "talk", "target": "雷电将军",
                  "utterance": "眼狩令之弊我已取证, 持眼者流离失所, 请废止它"},
    },
    (3, 19.0): {
        "雷电将军": {"action": "attack", "target": "旅行者"},
    },
    # 第4天: 再劝 (劝2)
    (4, 9.0): {
        "旅行者": {"action": "talk", "target": "雷电将军",
                  "utterance": "我已锻利刃、集实证, 将军容我再言一次"},
    },
    # 第5天: 三劝 (劝3) → 废止眼狩令 (结局)
    (5, 9.0): {
        "旅行者": {"action": "talk", "target": "雷电将军",
                  "utterance": "稻妻百姓苦眼狩令久矣, 望将军三思"},
    },
}


def _snapshot(w: World) -> dict:
    return {
        name: {"health": e.health, "loc": e.location.name, "dead": e.dead,
               "reasons": list(e.reasons), "attack": e.attack, "role": e.role,
               "kind": e.kind}
        for name, e in w.entities.items()
    }


def main() -> int:
    random.seed(20240521)   # 确定性: 攻击伤害的随机扰动可复现
    tmp = tempfile.mkdtemp()
    w = World("稻妻城", LOCATIONS, path=None)   # 内存世界, 不落库
    llm = _StubLLM()

    for name, traits, loc, hp, atk, dfn, role in NPCS:
        w.add_npc(name, traits, llm=llm, data_dir=tmp, location=loc)
        e = w.get(name)
        e.health, e.attack, e.defense, e.role = hp, atk, dfn, role
        w._agent_llms[name] = llm
        w._agent_personas[name] = traits
    w.add_agent_player("旅行者", "稻妻主城", "劝雷电将军废止眼狩令", llm=llm,
                       health=300, attack=12, defense=5)

    # 用脚本决策表替换 LLM 决策 (agent 按 (day, moment) 查表, 缺省观望)
    def scripted_decide(agent, memory_context: str = "") -> dict:
        day = int(w.clock // 24) + 1
        moment = round(w.clock % 24, 1)
        table = SCRIPT.get((day, moment), {})
        return table.get(agent.name, {"action": "wait", "reason": "脚本默认"})
    w.decide_agent = scripted_decide   # type: ignore[assignment]

    shogun = w.get("雷电将军")
    persuade_count = 0
    decree_ended = False
    last_persuade_day = -1
    timeline: list[dict] = []

    # 开场世界事件
    w.world_event("雷电将军颁布眼狩令: 全城神之眼一律收缴", now=7.0)
    timeline.append({"day": 0, "moment": 7.0, "clock": 7.0,
                     "events": [ve.describe() for ve in w.visual_events],
                     "visual_events": [ve.to_dict() for ve in w.visual_events],
                     "states": _snapshot(w), "persuade": 0, "decree_ended": False,
                     "shogun_dead": False})
    w.visual_events.clear()

    for day in range(1, DAYS + 1):
        for moment in MOMENTS:
            now = (day - 1) * 24.0 + moment
            events, decisions = w.step_autonomous(now)
            note = ""
            if shogun.dead:
                note = "★ 雷电将军阵亡! 眼狩令随将军倒台而废止。"
                decree_ended = True
            else:
                t_act = decisions.get("旅行者", {})
                if t_act.get("action") == "talk" and t_act.get("target") == "雷电将军":
                    trav = w.get("旅行者")
                    if len(trav.reasons) < REASON_NEEDED:
                        note = f"雷电将军驳回: '你既无实证' [理由{len(trav.reasons)}/{REASON_NEEDED}]"
                    elif trav.attack < ATTACK_NEEDED:
                        note = f"雷电将军驳回: '就凭你这副身板?' [攻{trav.attack}/{ATTACK_NEEDED}]"
                    elif day == last_persuade_day:
                        note = "雷电将军: '容我再想想。' 当天再劝无效"
                    else:
                        persuade_count += 1
                        last_persuade_day = day
                        note = f"当面劝说, 将军'容我考虑' — {persuade_count}/{PERSUADE_N}"
                if persuade_count >= PERSUADE_N and not shogun.dead:
                    w.world_event("雷电将军被旅行者说服, 废止眼狩令: 持眼者可保留神之眼", now=now)
                    note = f"★ 雷电将军被说服 (当面劝说 {persuade_count} 次), 废止眼狩令!"
                    decree_ended = True
            timeline.append({"day": day, "moment": moment, "clock": now,
                             "events": events,
                             "visual_events": [ve.to_dict() for ve in w.visual_events],
                             "note": note, "states": _snapshot(w),
                             "persuade": persuade_count, "decree_ended": decree_ended,
                             "shogun_dead": shogun.dead})
            w.visual_events.clear()
            if decree_ended or shogun.dead:
                break
        if decree_ended or shogun.dead:
            break

    out = {"schema_version": 1,
           "world": {"name": w.name, "coordinate_system": "location-name",
                     "render_map": "inazuma-v1"},
           "reason_needed": REASON_NEEDED, "attack_needed": ATTACK_NEEDED,
           "persuade_n": PERSUADE_N, "steps": timeline}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    w.close()

    # 汇总事件类型分布
    import collections
    kinds = collections.Counter()
    for s in timeline:
        for ve in s["visual_events"]:
            kinds[ve["type"]] += 1
    print(f"stub 时间线已生成: {os.path.abspath(OUT)}")
    print(f"步数: {len(timeline)}  事件类型分布: {dict(kinds)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
