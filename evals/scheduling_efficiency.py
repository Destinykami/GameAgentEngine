"""evals/scheduling_efficiency.py — 实验 3: 多 Agent 认知调度效率 (cost↔quality trade-off)。

配置:
  all_full       全员全认知 + 无决策门控 (现系统自治循环原样: 每 NPC 每步 LLM 决策)
  tiered         距离三级调度 + idle 决策门控 (P8: 视距内无人时远处 NPC 规则等待, 零 LLM)
  tiered_capped  tiered + 反思候选证据相关性下限 (P1 evidence_min_relevance=0.5)

世界: 稻妻 6 区域 + N 个 NPC (5 原型, 将军唯一, 其余轮换扩展) + 1 个 LLM 自治旅行者,
3 天 × 8 步 (24 步), 世界事件逐级升级 (眼狩令 → 眼狩署搜捕 → 全图清剿)。
每 NPC 独立 RealLLM 实例 → usage 计数器天然 per-NPC 归属; 嵌入用 HashEmbedder
(零延迟, 不污染 LLM 延迟测量 —— 与实验 1/2 用真实嵌入刻意不同)。

指标: LLM Calls / Tokens per Step / P50-P95 Step Latency / by_method 成本拆解 /
Decision Consistency (旅行者决策序列逐步一致率 + 终局世界状态比对) /
认知深度代价 (自我反思条数差) / NPC Count Scaling (N=5/10/20/40)。

跑法: .venv/bin/python evals/scheduling_efficiency.py --smoke  (N=2×2步, ~2 分钟)
      .venv/bin/python evals/scheduling_efficiency.py          (全量, ~45-60 分钟)
产物: data/eval/scheduling_efficiency/<时间戳>/{runs,metrics}.json (不入库)
"""

from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

from persona_agent import World, Location, HashEmbedder
from common import (llm_available, fresh_llm, run_dir, save_json,
                    print_table, pct)

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
            npc.reflection._evidence_min_relevance = CAP_MIN_RELEVANCE
        e = w.get(name)
        e.health, e.attack, e.defense, e.goal = hp, atk, dfn, goal
        w._agent_llms[name] = llm        # 同 world_auto_sim 的自治注册惯例
        w._agent_personas[name] = dict(traits)
    t_llm = fresh_llm()
    llms["旅行者"] = t_llm
    w.add_agent_player("旅行者", "稻妻主城", TRAVELER_GOAL, llm=t_llm,
                       persona_traits={"social": 0.5, "goal_oriented": 0.9},
                       health=380, attack=12, defense=5)
    return w, llms


def sum_usage(llms) -> dict:
    """跨实例汇总 usage (calls/tokens/latency)。"""
    total = {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0}
    by_method: dict = {}
    for llm in llms.values():
        s = llm.stats
        total["calls"] += s["calls"]
        total["prompt_tokens"] += s["prompt_tokens"]
        total["completion_tokens"] += s["completion_tokens"]
        for m, per in s["by_method"].items():
            b = by_method.setdefault(m, {"calls": 0, "prompt_tokens": 0,
                                         "completion_tokens": 0})
            b["calls"] += per["calls"]
            b["prompt_tokens"] += per["prompt_tokens"]
            b["completion_tokens"] += per["completion_tokens"]
    total["by_method"] = by_method
    return total


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
                      (("full", sum(1 for x in w._npcs.values() if x.tier == "full")),
                       ("compressed", sum(1 for x in w._npcs.values()
                                          if x.tier == "compressed")),
                       ("idle", sum(1 for x in w._npcs.values()
                                    if x.tier == "idle")))},
        })
        traveler_actions.append(decisions.get("旅行者", {}).get("action", "wait"))
    # ------------------------------------------------------------- 收尾
    shogun = w.get("雷电将军")
    outcome = {
        "npcs_alive": sum(1 for x in w._npcs.values()
                          if w.entities[x.name].is_alive()),
        "n": n,
        "traveler_attack": w.get("旅行者").attack,
        "traveler_reasons": len(w.get("旅行者").reasons),
        "shogun_health": shogun.health if shogun else None,
        "shogun_dead": bool(shogun.dead) if shogun else None,
        "self_reflections_total": sum(
            len(npc.store.all_valid(types=["reflection"], shared=True))
            for npc in w._npcs.values()),
    }
    total = sum_usage(llms)
    return {"config": config, "n": n, "steps": step_costs,
            "traveler_actions": traveler_actions, "outcome": outcome,
            "total_usage": total}


def percentile(values: list, p: float) -> float:
    if not values:
        return 0.0
    vs = sorted(values)
    k = (len(vs) - 1) * p
    f, c = int(k), min(int(k) + 1, len(vs) - 1)
    return vs[f] + (vs[c] - vs[f]) * (k - f)


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


if __name__ == "__main__":
    sys.exit(main())
