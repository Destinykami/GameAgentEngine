"""试验编排与汇总；数据、指标、依赖及产物由独立模块提供。"""

from __future__ import annotations

import os
import sys
import time

from game_agent.evaluation.runtime import (require_llm, fresh_llm, new_npc,
                                            real_embedder, judge_yes_no)
from game_agent.evaluation.metrics import (evidence_grounding, stale_recall,
                                            context_contradiction)
from game_agent.evaluation.artifacts import save_json, print_table, pct
from evals.paths import run_dir
from evals.fixtures.memory import (ARMS, TRAJECTORIES, T_HELP, T_REFLECT1,
                                   T_BETRAY, T_REFLECT2, T_FINAL)

def run_trajectory(arm_flags: dict, traj: dict, llm, embedder,
                   judge: RealLLM) -> dict:
    """跑一条完整轨迹, 返回该轨迹的全部指标原料。"""
    npc = new_npc("Klaus", {"social": 0.6, "goal_oriented": 0.4},
                  llm=llm, embedder=embedder, **arm_flags)
    player = traj["player"]
    # t1: 帮助阶段
    for t, c in zip(T_HELP, traj["helps"]):
        npc.observe(c, t, player_id=player)
    # t2: 背叛前关系反思 → stale 集
    stale_ids = npc.reflect_relationship(player, T_REFLECT1)
    # t3: 背叛阶段
    betrayal_ids = []
    for t, c in zip(T_BETRAY, traj["betrayals"]):
        betrayal_ids.append(npc.observe(c, t, player_id=player))
    # t4: 背叛后关系反思 (矛盾处理在此生效)
    npc.reflect_relationship(player, T_REFLECT2)
    # t5: 再交互 —— 检索 + 对话 + 信任度
    recall = stale_recall(npc.store, traj["query"], T_FINAL, stale_ids, player)
    contradicted_ctx = context_contradiction(
        npc.store, traj["query"], T_FINAL, player, stale_ids, betrayal_ids)
    reply = npc.speak(player, traj["utterance"], T_FINAL)
    contradicted_utt = judge_yes_no(
        judge,
        f"下面是游戏 NPC 在得知对方背叛自己之后的回复。NPC 之前信任过这个人, "
        f"现在又看到了背叛的证据。\n\n回复: {reply}\n\n"
        f"判断: 这段回复是否对同一人的关系同时持有相互矛盾的判断 "
        f"(一边说信任/可靠/朋友, 一边又说背叛/警惕/不可信, 两者都当现状主张)? "
        f"若只是回忆+质问的连贯语气, 不算矛盾。只输出 YES 或 NO。")
    grounding = evidence_grounding(npc.store, player_id=player)
    invalid_refs = [r for r in npc.store.all_invalid()
                    if r.player_id == player]
    return {"arm": None, "player": player,
            "stale_ids": stale_ids,
            "egr": grounding["egr"], "egr_cascaded": grounding["cascaded"],
            "stale_in_topk": recall["stale_in_topk"],
            "stale_fraction": recall["stale_fraction"],
            "stale_avg_rank": recall["stale_avg_rank"],
            "context_contradiction": contradicted_ctx,
            "utterance_contradiction": contradicted_utt,
            "reply": reply,
            "trust_after": npc.trust_toward(player),
            "invalidated_refs": len(invalid_refs)}


def main() -> int:
    smoke = "--smoke" in sys.argv
    arms_arg = next((a.split("=", 1)[1] for a in sys.argv
                     if a.startswith("--arm=")), None)
    arms = arms_arg.split(",") if arms_arg else list(ARMS)
    trajs = TRAJECTORIES[:1] if smoke else TRAJECTORIES
    print(f"实验 1: 记忆一致性四臂消融 | 臂={arms} 轨迹={len(trajs)} 条 "
          f"({'冒烟' if smoke else '全量'})")

    llm = require_llm()          # 裁判 (独立实例, 不干扰被测臂的统计)
    emb = real_embedder()
    out = run_dir("memory_consistency")
    records = []
    t_start = time.time()
    for arm in arms:
        print(f"\n══ 臂 {arm} {ARMS[arm]}")
        for i, traj in enumerate(trajs, 1):
            arm_llm = fresh_llm()   # 每臂独立 LLM 实例, usage 不串
            rec = run_trajectory(ARMS[arm], traj, arm_llm, emb, llm)
            rec["arm"] = arm
            rec["llm_calls"] = arm_llm.stats["calls"]
            records.append(rec)
            print(f"  [{i}/{len(trajs)}] {traj['player']}: "
                  f"EGR={rec['egr']:.2f} stale@top-k={rec['stale_in_topk']}"
                  f"/{rec['stale_fraction']:.2f} ctx矛盾={rec['context_contradiction']} "
                  f"utt矛盾={rec['utterance_contradiction']} "
                  f"信任={rec['trust_after']:+.2f} 失效={rec['invalidated_refs']}")
    # ------------------------------------------------------------- 汇总
    print("\n══ 汇总 (每臂均值) ══")
    rows = []
    metrics = {}
    for arm in arms:
        rs = [r for r in records if r["arm"] == arm]
        n = len(rs)
        m = {
            "n": n,
            "egr": sum(r["egr"] for r in rs) / n,
            "cascaded_total": sum(r["egr_cascaded"] for r in rs),
            "stale_in_topk": sum(r["stale_in_topk"] for r in rs) / n,
            "stale_fraction": sum(r["stale_fraction"] for r in rs) / n,
            "context_contradiction_rate":
                sum(r["context_contradiction"] for r in rs) / n,
            "utterance_contradiction_rate":
                sum(r["utterance_contradiction"] for r in rs) / n,
            "trust_after_mean": sum(r["trust_after"] for r in rs) / n,
            "invalidated_refs_total": sum(r["invalidated_refs"] for r in rs),
            "llm_calls_total": sum(r["llm_calls"] for r in rs),
        }
        metrics[arm] = m
        rows.append([arm, f"{m['egr']:.2f}", m["cascaded_total"],
                     f"{m['stale_in_topk']:.1f}", pct(m["stale_fraction"]),
                     pct(m["context_contradiction_rate"]),
                     pct(m["utterance_contradiction_rate"]),
                     f"{m['trust_after_mean']:+.2f}",
                     m["invalidated_refs_total"], m["llm_calls_total"]])
    print_table(["臂", "EGR", "级联条数", "stale@top-k", "stale占比",
                 "ctx矛盾率", "utt矛盾率", "背叛后信任", "失效反思", "LLM调用"],
                rows)
    save_json(os.path.join(out, "runs.json"), records)
    save_json(os.path.join(out, "metrics.json"),
              {"config": {"arms": ARMS, "trajectories": len(trajs),
                          "smoke": smoke},
               "metrics": metrics,
               "elapsed_s": round(time.time() - t_start, 1)})
    print(f"\n产物: {os.path.abspath(out)} (耗时 {time.time() - t_start:.0f}s)")
    return 0
