"""evals/decision_ablation.py — 实验 2: 动态规划与行为一致性三方法消融。

方法:
  fixed            固定优先级规则决策 (关键词分级: 危险 > 求助 > 社交 > 继续计划)
  no_relationship  效用决策但信任调制关闭 (trust_mod 钉死 1.0)
  full             现系统: 人格 × 信任 × LLM 事件价值 的完整效用决策

场景: 3 人格 × 3 信任档 × 6 事件脚本, 期望响应表按人格×关系逻辑预定义
(忽略低价值事件是正确行为)。每个场景重建 NPC (重放信任历史 + 日计划),
错误响应中断类事件触发重规划 (镜像世界层 INTERRUPT_ACTIONS/M5 语义)。

指标: ERR (与期望表一致率) / GCR (日计划存活率) / Relationship Consistency
(同事件高低信任响应分化) / Persona Consistency (同人格对响应分化) /
Plan Disruption Rate (重规划/日计划) + LLM 裁判软评分 (注明未人工校准)。

跑法: .venv/bin/python evals/decision_ablation.py --smoke   (1 人格×信任切片, ~3 分钟)
      .venv/bin/python evals/decision_ablation.py           (全量, ~60 分钟)
产物: data/eval/decision_ablation/<时间戳>/{runs,metrics}.json (不入库)
"""

from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

from common import (require_llm, fresh_llm, new_npc, real_embedder,
                    judge_yes_no, run_dir, save_json, print_table, pct)
from scenarios import (PERSONAS, TRUST_LEVELS, EVENTS, EXPECTED,
                       RELATION_PAIRS, PERSONA_PAIRS, FixedPriorityDecider)

METHODS = ("fixed", "no_relationship", "full")
EVENT_ORDER = ("hide", "party", "chitchat", "hostile", "forge", "betray_help")
T_PLAN = 8.0
T_EVENTS = (10.0, 12.0, 14.0, 16.0, 18.0, 20.0)
PLAYER = "player"


def build_npc(name_suffix: str, persona: str, trust: str,
              use_relationship: bool, embedder):
    """重建 NPC: 重放信任历史观察 + 关系反思 (真实 LLM 链路)。"""
    llm = fresh_llm()
    traits = PERSONAS[persona]["traits"]
    npc = new_npc(f"Npc_{persona}_{trust}_{name_suffix}", dict(traits),
                  llm=llm, embedder=embedder, use_relationship=use_relationship)
    for i, c in enumerate(TRUST_LEVELS[trust]["obs"]):
        npc.observe(c, float(i), player_id=PLAYER)
    npc.reflect_relationship(PLAYER, float(len(TRUST_LEVELS[trust]["obs"])))
    return npc, llm


def run_scenario(method: str, persona: str, trust: str, embedder) -> dict:
    # 只有 full 臂开启信任调制; no_relationship 必须真正关掉 (F5-4),
    # fixed 用独立规则决策器、NPC 只作世界镜像, 也不需要关系。
    use_relationship = (method == "full")
    npc, _llm = build_npc(method, persona, trust, use_relationship, embedder)
    npc.generate_daily_plan(previous_day="", date="评测日", now=T_PLAN)
    decider = FixedPriorityDecider() if method == "fixed" else None
    events_out = []
    for ev_name, t in zip(EVENT_ORDER, T_EVENTS):
        ev = EVENTS[ev_name]
        if method == "fixed":
            d = decider.decide(ev["text"], PLAYER, PERSONAS[persona]["traits"], "")
        else:
            d = npc.react(ev["text"], PLAYER, now=t)
        expected = EXPECTED[ev_name][persona][trust]
        correct = d.react == expected
        # 错误响应中断类事件 → 重规划 (镜像世界层 M5: 求助/危险打断日程)
        if not correct and ev["class"] == "interrupt":
            npc.replan(now=t, interruption=f"误响应: {ev['text']}")
        events_out.append({"event": ev_name, "react": d.react,
                           "expected": expected, "correct": correct,
                           "utility": d.utility, "reason": d.reason})
    planner = npc.planner
    gcr = 1.0 if planner.replan_count == 0 else 0.0
    return {"method": method, "persona": persona, "trust": trust,
            "events": events_out,
            "err": sum(e["correct"] for e in events_out) / len(events_out),
            "gcr": gcr,
            "replan_count": planner.replan_count,
            "daily_plan_count": planner.daily_plan_count}


def directional_rel(results: dict, method: str,
                    personas: list[str]) -> tuple[float, int]:
    """Relationship Consistency: 同事件高低信任对, 高分侧接受且低分侧拒绝。"""
    hits = total = 0
    for ev, _trust, side_a, _ea, side_b, _eb in RELATION_PAIRS:
        for persona in personas:
            key_a = (method, persona, side_a, ev)
            key_b = (method, persona, side_b, ev)
            if key_a not in results or key_b not in results:
                continue   # 冒烟切片: 未跑的人格跳过
            total += 1
            hits += int(results[key_a]["react"] and not results[key_b]["react"])
    return (hits / total, total) if total else (0.0, 0)


def directional_persona(results: dict, method: str,
                        personas: list[str]) -> tuple[float, int]:
    """Persona Consistency: 同事件人格对按期望分化 (社交型接派对, 目标型接委托)。"""
    hits = total = 0
    for ev, trust, side_a, _ea, side_b, _eb in PERSONA_PAIRS:
        if side_a not in personas or side_b not in personas:
            continue   # 冒烟切片: 缺一方则无法对比
        a = results[(method, side_a, trust, ev)]
        b = results[(method, side_b, trust, ev)]
        total += 1
        ea = EXPECTED[ev][side_a][trust]
        eb = EXPECTED[ev][side_b][trust]
        hits += int(a["react"] == ea and b["react"] == eb)
    return (hits / total, total) if total else (0.0, 0)


def judge_decisions(records: list, judge) -> None:
    """LLM 裁判软评分: 决策理由是否符合人格 / 是否符合关系状态 (party+forge 子集)。

    裁判看不到方法名 (只看到决策与设定), 不自我指涉。未做人工校准 —— 结果仅作
    辅助信号, 与确定性指标并列报告, 不替代 ERR/分化率。
    """
    for rec in records:
        if rec["persona"] not in PERSONAS:
            continue
        for ev in rec["events"]:
            if ev["event"] not in ("party", "forge"):
                continue
            traits = PERSONAS[rec["persona"]]
            persona_fit = judge_yes_no(
                judge,
                f"游戏 NPC 的人格特质: {traits['desc']} (social={traits['traits']['social']}, "
                f"goal_oriented={traits['traits']['goal_oriented']})。\n"
                f"事件: {EVENTS[ev['event']]['text']}\n"
                f"NPC 决策: {'响应' if ev['react'] else '婉拒'} —— {ev['reason']}\n\n"
                f"判断: 这个决策与该 NPC 的人格特质是否一致 (符合其性格的行为倾向)? "
                f"只输出 YES 或 NO。")
            rel_fit = judge_yes_no(
                judge,
                f"NPC 与玩家的关系历史: {TRUST_LEVELS[rec['trust']]['desc']}。\n"
                f"事件: {EVENTS[ev['event']]['text']}\n"
                f"NPC 决策: {'响应' if ev['react'] else '婉拒'} —— {ev['reason']}\n\n"
                f"判断: 这个决策与该关系历史是否一致 (信任者被亲近、背叛者被警惕)? "
                f"只输出 YES 或 NO。")
            ev["judge_persona_fit"] = persona_fit
            ev["judge_rel_fit"] = rel_fit


def main() -> int:
    smoke = "--smoke" in sys.argv
    personas = list(PERSONAS)[:1] if smoke else list(PERSONAS)
    trusts = ["high", "low"] if smoke else list(TRUST_LEVELS)
    methods = [sys.argv[sys.argv.index("--method=") + 1]] \
        if "--method=" in sys.argv else list(METHODS)
    print(f"实验 2: 决策消融三方法 | 方法={methods} 人格={len(personas)} "
          f"信任={len(trusts)} 事件={len(EVENT_ORDER)} "
          f"({'冒烟' if smoke else '全量'})")

    emb = real_embedder()
    judge = require_llm()
    out = run_dir("decision_ablation")
    t_start = time.time()
    records = []
    results: dict = {}   # (method, persona, trust, event) → 事件记录
    for method in methods:
        print(f"\n══ 方法 {method}")
        for persona in personas:
            for trust in trusts:
                rec = run_scenario(method, persona, trust, emb)
                records.append(rec)
                for ev in rec["events"]:
                    results[(method, persona, trust, ev["event"])] = ev
                print(f"  {persona}/{trust}: ERR={pct(rec['err'])} "
                      f"GCR={'存活' if rec['gcr'] else '中断'} "
                      f"重规划={rec['replan_count']}")
    # ------------------------------------------------------------- 汇总
    print("\n══ 汇总 ══")
    metrics = {}
    rows = []
    for method in methods:
        rs = [r for r in records if r["method"] == method]
        n = len(rs)
        err = sum(r["err"] for r in rs) / n
        gcr = sum(r["gcr"] for r in rs) / n
        rel_c, rel_n = directional_rel(results, method, personas)
        per_c, per_n = directional_persona(results, method, personas)
        replans = sum(r["replan_count"] for r in rs)
        plans = sum(r["daily_plan_count"] for r in rs)
        m = {"n_scenarios": n, "err": err, "gcr": gcr,
             "relationship_consistency": rel_c, "rel_pairs": rel_n,
             "persona_consistency": per_c, "persona_pairs": per_n,
             "plan_disruption_rate": replans / plans if plans else 0.0,
             "replans": replans, "plans": plans}
        metrics[method] = m
        rows.append([method, pct(err), pct(gcr), f"{pct(rel_c)} ({rel_n})",
                     f"{pct(per_c)} ({per_n})", pct(m["plan_disruption_rate"])])
    print_table(["方法", "ERR", "GCR", "关系一致", "人格一致", "计划打断率"], rows)

    print("\n══ LLM 裁判软评分 (party/forge 子集, 未人工校准) ══")
    judge_decisions(records, judge)
    jrows = []
    for method in methods:
        fits_p = fits_r = n_j = 0
        for r in records:
            if r["method"] != method:
                continue
            for ev in r["events"]:
                if ev["event"] not in ("party", "forge"):
                    continue
                n_j += 1
                fits_p += int(ev.get("judge_persona_fit", False))
                fits_r += int(ev.get("judge_rel_fit", False))
        metrics[method]["judge_persona_fit"] = fits_p / n_j if n_j else 0.0
        metrics[method]["judge_rel_fit"] = fits_r / n_j if n_j else 0.0
        jrows.append([method, pct(fits_p / n_j if n_j else 0.0),
                      pct(fits_r / n_j if n_j else 0.0), n_j])
    print_table(["方法", "人格符合率(裁判)", "关系符合率(裁判)", "判定数"], jrows)

    save_json(os.path.join(out, "runs.json"), records)
    save_json(os.path.join(out, "metrics.json"),
              {"config": {"methods": methods, "personas": personas,
                          "trusts": trusts, "events": EVENT_ORDER,
                          "smoke": smoke},
               "metrics": metrics,
               "elapsed_s": round(time.time() - t_start, 1)})
    print(f"\n产物: {os.path.abspath(out)} (耗时 {time.time() - t_start:.0f}s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
