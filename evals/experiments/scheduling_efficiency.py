"""试验编排与汇总；数据、指标、依赖及产物由独立模块提供。"""

from __future__ import annotations

import os
import sys
import time

from game_agent import World, HashEmbedder
from game_agent.evaluation.runtime import llm_available, fresh_llm
from game_agent.evaluation.artifacts import save_json, print_table, pct
from game_agent.evaluation.metrics import sum_usage, percentile
from evals.paths import run_dir
from evals.fixtures.scheduling import (LOCATIONS, LOC_NAMES, ARCHETYPES, SHOGUN,
                                      TRAVELER_GOAL, CONFIGS, NS_FULL, NS_TIERED,
                                      NS_CAPPED, DAYS, MOMENTS, REFLECT_THRESHOLD,
                                      CAP_MIN_RELEVANCE)

def timeline():
    return [d * 24 + m for d in range(DAYS) for m in MOMENTS]


def expand_roster(n: int) -> list:
    """N 个 NPC: 将军唯一 + 4 原型按序轮换 (副本带编号后缀)。"""
    rosters = [SHOGUN]
    while len(rosters) < n:
        base = ARCHETYPES[len(rosters) % len(ARCHETYPES)]
        tag = f"-{len(rosters) - 4}" if len(rosters) >= 5 else ""
        rosters.append((base[0] + tag, base[1], base[2], base[3],
                        base[4], base[5], base[6]))
    return rosters[:n]


def build_world(config: str, n: int, emb):
    """建一个内存世界: N 个 NPC (独立 LLM 实例) + 自治旅行者。

    NPC 各自独立 db 目录 (每 配置×N 全新, 防 NPC.create 加载上轮残留记忆)。
    """
    import shutil
    cfg = CONFIGS[config]
    w = World("稻妻城", LOCATIONS, force_full_tier=cfg["force_full_tier"],
              decision_tier_gate=cfg["decision_tier_gate"])
    w.reason_cap = 6
    llms = {}
    data_dir = os.path.join(run_dir("scheduling_efficiency"), "_worlds",
                            f"{config}_N{n}")
    shutil.rmtree(data_dir, ignore_errors=True)
    for name, traits, loc, hp, atk, dfn, goal in expand_roster(n):
        llm = fresh_llm()
        llms[name] = llm
        npc = w.add_npc(name, dict(traits), llm=llm, embedder=emb,
                        data_dir=data_dir, location=loc,
                        reflection_threshold=REFLECT_THRESHOLD)
        if cfg["capped"]:
            # 候选证据限制: 反思证据检索的相关性下限 (top_k 保持 10, 未另设参数)
            npc.reflection.evidence_min_relevance = CAP_MIN_RELEVANCE
        e = w.get(name)
        e.health, e.attack, e.defense, e.goal = hp, atk, dfn, goal
        w.register_agent(name, llm, dict(traits))
    t_llm = fresh_llm()
    llms["旅行者"] = t_llm
    w.add_agent_player("旅行者", "稻妻主城", TRAVELER_GOAL, llm=t_llm,
                       persona_traits={"social": 0.5, "goal_oriented": 0.9},
                       health=380, attack=12, defense=5)
    return w, llms


def run_config(config: str, n: int, emb, tl: list) -> dict:
    """跑一个配置×N 的完整模拟, 逐步记录成本, 收尾取世界状态。"""
    w, llms = build_world(config, n, emb)
    # 开场世界事件: 眼狩令生效 (全图)
    w.world_event("雷电将军颁布眼狩令, 收缴神之眼", now=1.0)
    step_costs = []
    traveler_actions = []
    for i, now in enumerate(tl):
        # 世界事件升级: 第 1 天搜捕 (眼狩署半径), 第 2 天清剿 (全图)
        if now == 25.0:
            w.world_event("执行官在眼狩署展开搜捕", now=now, at="眼狩署", radius=2.0)
        elif now == 49.0:
            w.world_event("全城大搜捕, 见持眼者即收", now=now)
        pre = sum_usage(llms)
        t0 = time.monotonic()
        _events, decisions = w.step_autonomous(now=now)
        latency = time.monotonic() - t0
        post = sum_usage(llms)
        step_costs.append({
            "step": i, "clock": now, "latency_s": round(latency, 2),
            "calls": post["calls"] - pre["calls"],
            "prompt_tokens": post["prompt_tokens"] - pre["prompt_tokens"],
            "completion_tokens": post["completion_tokens"] - pre["completion_tokens"],
            "tiers": {k: v for k, v in
                      (("full", sum(1 for x in (w.npc(name) for name in w.npc_names()) if x.tier == "full")),
                       ("compressed", sum(1 for x in (w.npc(name) for name in w.npc_names())
                                          if x.tier == "compressed")),
                       ("idle", sum(1 for x in (w.npc(name) for name in w.npc_names())
                                    if x.tier == "idle")))},
        })
        traveler_actions.append(decisions.get("旅行者", {}).get("action", "wait"))
    # ------------------------------------------------------------- 收尾
    shogun = w.get("雷电将军")
    outcome = {
        "npcs_alive": sum(1 for x in (w.npc(name) for name in w.npc_names())
                          if w.entities[x.name].is_alive()),
        "n": n,
        "traveler_attack": w.get("旅行者").attack,
        "traveler_reasons": len(w.get("旅行者").reasons),
        "shogun_health": shogun.health if shogun else None,
        "shogun_dead": bool(shogun.dead) if shogun else None,
        "self_reflections_total": sum(
            len(npc.store.all_valid(types=["reflection"], shared=True))
            for npc in (w.npc(name) for name in w.npc_names())),
    }
    total = sum_usage(llms)
    return {"config": config, "n": n, "steps": step_costs,
            "traveler_actions": traveler_actions, "outcome": outcome,
            "total_usage": total}


def main() -> int:
    smoke = "--smoke" in sys.argv
    only_arg = next((a.split("=", 1)[1] for a in sys.argv
                     if a.startswith("--only=")), None)
    configs = only_arg.split(",") if only_arg else list(CONFIGS)
    tl = [7.0, 9.0] if smoke else timeline()   # 冒烟: 压缩时间轴
    ns_cfg = (2,) if smoke else tuple(dict.fromkeys(NS_FULL + NS_TIERED))
    days_label = "冒烟(2步)" if smoke else f"全量({DAYS}天×{len(MOMENTS)}步)"
    print(f"实验 3: 认知调度效率 | 配置={list(CONFIGS)} N={ns_cfg} {days_label}")
    emb = HashEmbedder()   # 零延迟嵌入, 保 LLM 延迟测量干净
    if not llm_available():
        raise RuntimeError("LLM 端点不可达 — 实验 3 需要真实 LLM")
    out = run_dir("scheduling_efficiency")
    runs = []
    t_start = time.time()
    for config in configs:
        if smoke:
            ns = (2,)
        else:
            ns = {"all_full": NS_FULL, "tiered": NS_TIERED,
                  "tiered_capped": NS_CAPPED}[config]
        for n in ns:
            t0 = time.monotonic()
            run = run_config(config, n, emb, tl)
            lat = [s["latency_s"] for s in run["steps"]]
            calls = [s["calls"] for s in run["steps"]]
            toks = [s["prompt_tokens"] + s["completion_tokens"] for s in run["steps"]]
            runs.append(run)
            # 增量保存: 每个配置×N 完成即落盘, 中途被打断不丢已完成进度
            save_json(os.path.join(out, "runs_partial.json"),
                      [{k: r[k] for k in ("config", "n", "steps",
                                          "traveler_actions", "outcome",
                                          "total_usage")} for r in runs])
            print(f"  {config} N={n}: 总调用={run['total_usage']['calls']} "
                  f"总token={sum(toks)} P50={percentile(lat, .5):.1f}s "
                  f"P95={percentile(lat, .95):.1f}s "
                  f"存活={run['outcome']['npcs_alive']}/{n} "
                  f"自我反思={run['outcome']['self_reflections_total']} "
                  f"(墙钟 {time.monotonic() - t0:.0f}s)")
    # ------------------------------------------------------------- 汇总
    metrics = {}
    rows = []
    for run in runs:
        lat = [s["latency_s"] for s in run["steps"]]
        calls = [s["calls"] for s in run["steps"]]
        toks = [s["prompt_tokens"] + s["completion_tokens"] for s in run["steps"]]
        m = {"n": run["n"],
             "total_calls": run["total_usage"]["calls"],
             "total_tokens": sum(toks),
             "calls_per_step_mean": sum(calls) / len(calls),
             "calls_per_step_peak": max(calls),
             "tokens_per_step_mean": sum(toks) / len(toks),
             "latency_p50": round(percentile(lat, 0.5), 2),
             "latency_p95": round(percentile(lat, 0.95), 2),
             "by_method": run["total_usage"]["by_method"],
             "outcome": run["outcome"]}
        metrics[f"{run['config']}_N{run['n']}"] = m
        rows.append([run["config"], run["n"], m["total_calls"],
                     int(m["calls_per_step_mean"]), m["calls_per_step_peak"],
                     int(m["tokens_per_step_mean"]), m["latency_p50"],
                     m["latency_p95"], run["outcome"]["self_reflections_total"]])
    print("\n══ 成本与延迟汇总 ══")
    print_table(["配置", "N", "总调用", "调用/步均值", "调用/步峰值",
                 "token/步均值", "P50延迟s", "P95延迟s", "自我反思总数"], rows)

    # Decision Consistency: 同 N 下 all_full vs tiered 的旅行者决策序列一致率
    print("\n══ 决策一致性 (旅行者决策序列, 同 N 配置对) ══")
    consistency = {}
    crows = []
    for n in dict.fromkeys(r["n"] for r in runs):
        af = next((r for r in runs if r["config"] == "all_full" and r["n"] == n), None)
        td = next((r for r in runs if r["config"] == "tiered" and r["n"] == n), None)
        if af and td and len(af["traveler_actions"]) == len(td["traveler_actions"]):
            agree = sum(1 for a, b in zip(af["traveler_actions"], td["traveler_actions"])
                        if a == b) / len(af["traveler_actions"])
            consistency[f"N{n}"] = {"agree": round(agree, 3),
                                    "steps": len(af["traveler_actions"]),
                                    "all_full_outcome": af["outcome"],
                                    "tiered_outcome": td["outcome"]}
            crows.append([n, f"{agree * 100:.1f}%",
                          af["outcome"]["shogun_health"], td["outcome"]["shogun_health"],
                          af["outcome"]["traveler_reasons"], td["outcome"]["traveler_reasons"]])
    if crows:
        print_table(["N", "决策一致率", "将军血(af)", "将军血(td)",
                     "理由数(af)", "理由数(td)"], crows)
    save_json(os.path.join(out, "runs.json"),
              [{k: r[k] for k in ("config", "n", "steps", "traveler_actions",
                                  "outcome", "total_usage")} for r in runs])
    save_json(os.path.join(out, "metrics.json"),
              {"config": {"configs": CONFIGS,
                          "n": {"all_full": NS_FULL, "tiered": NS_TIERED,
                                "tiered_capped": NS_CAPPED} if not smoke
                          else {"smoke": True},
                          "days": DAYS if not smoke else None},
               "metrics": metrics,
               "decision_consistency": consistency,
               "elapsed_s": round(time.time() - t_start, 1)})
    print(f"\n产物: {os.path.abspath(out)} (耗时 {time.time() - t_start:.0f}s)")
    return 0
