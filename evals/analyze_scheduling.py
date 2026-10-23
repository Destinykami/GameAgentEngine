"""evals/analyze_scheduling.py — 合并调度实验的两段运行目录, 出最终报告数据。

数据源: data/eval/scheduling_efficiency/<runA>/runs_partial.json (all_full N=5 +
旧 tiered 5/10, 修复前) 与 <runB>/runs_partial.json (tiered 5/10/20/40 + capped 40,
修复后, 同进程一致性)。tiered 取 runB (修复后), all_full 取 runA。
输出: 成本/延迟表、by_method 成本拆解、N=5 决策一致性 (含噪声上界说明)、认知深度。
用法: .venv/bin/python evals/analyze_scheduling.py <runA> <runB>
"""

from __future__ import annotations

import os
import sys

from game_agent.evaluation.metrics import percentile
from game_agent.evaluation.artifacts import load_json


def load(dirpath: str) -> list:
    p = os.path.join(dirpath, "runs_partial.json")
    if not os.path.exists(p):
        return []
    return load_json(p)




def main() -> int:
    run_a, run_b = sys.argv[1], sys.argv[2]
    a = load(run_a)
    b = load(run_b)
    # 组装最终数据集: tiered 系取 runB, all_full 取 runA
    final = [r for r in a if r["config"] == "all_full"]
    final += [r for r in b if r["config"] != "all_full"]
    final.sort(key=lambda r: (r["config"], r["n"]))
    print(f"\n══ 调度实验最终数据 (runA={os.path.basename(run_a)}, "
          f"runB={os.path.basename(run_b)}) ══")
    print(f"\n── 成本与延迟 ──")
    print(f"{'配置':<15}{'N':>4}{'总调用':>8}{'调用/步均值':>12}{'token/步均值':>12}"
          f"{'P50s':>8}{'P95s':>8}{'自我反思':>8}")
    for r in final:
        lat = [s["latency_s"] for s in r["steps"]]
        calls = [s["calls"] for s in r["steps"]]
        toks = [s["prompt_tokens"] + s["completion_tokens"] for s in r["steps"]]
        u = r["total_usage"]
        print(f"{r['config']:<15}{r['n']:>4}{u['calls']:>8}"
              f"{sum(calls) / len(calls):>12.1f}{sum(toks) / len(toks):>12.0f}"
              f"{percentile(lat, .5):>8.1f}{percentile(lat, .95):>8.1f}"
              f"{r['outcome']['self_reflections_total']:>8}")
    print("\n── by_method 成本拆解 (总调用占比) ──")
    for r in final:
        bm = r["total_usage"]["by_method"]
        total = r["total_usage"]["calls"]
        top = sorted(bm.items(), key=lambda kv: -kv[1]["calls"])[:6]
        parts = ", ".join(f"{m}={v['calls']}({v['calls'] * 100 // total}%)"
                          for m, v in top)
        print(f"  {r['config']} N={r['n']}: {parts}")
    print("\n── 旅行者决策一致性 (N=5, all_full vs tiered, 独立世界) ──")
    af = next((r for r in a if r["config"] == "all_full" and r["n"] == 5), None)
    td = next((r for r in b if r["config"] == "tiered" and r["n"] == 5), None)
    if af and td:
        sa, sb = af["traveler_actions"], td["traveler_actions"]
        agree = sum(1 for x, y in zip(sa, sb) if x == y) / len(sa)
        from collections import Counter
        print(f"  逐步一致率: {agree * 100:.1f}% ({len(sa)} 步)")
        print(f"  all_full 动作分布: {dict(Counter(sa))}")
        print(f"  tiered   动作分布: {dict(Counter(sb))}")
        oa, ob = af["outcome"], td["outcome"]
        print(f"  终局: 存活 {oa['npcs_alive']}/{ob['npcs_alive']}, "
              f"将军血 {oa['shogun_health']}/{ob['shogun_health']}, "
              f"理由数 {oa['traveler_reasons']}/{ob['traveler_reasons']}")
    print("\n  注意: 两臂是各自独立世界的单次运行, LLM 随机采样 (temperature>0) 自带"
          "序列噪声, 一致率是'调度配置改变旅行者体验程度'的上界, 非严格反事实。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
