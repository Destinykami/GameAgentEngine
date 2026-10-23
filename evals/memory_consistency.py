"""evals/memory_consistency.py — 实验 1: 长期记忆一致性四臂消融。

轨迹 (每条): t0-4 玩家帮助 (2-3 观察) → t6 关系反思 (产出 stale 集) →
t8-10 玩家背叛 (1-2 观察) → t12 关系反思 (矛盾处理在此生效) → t20 再交互
(关系相关查询检索 + speak 对话)。四臂:

  baseline    原始反思 (证据可引用反思) + 无矛盾处理
  ablation_a  证据约束反思 + 无矛盾处理        —— 隔离级联切断
  ablation_b  原始反思 + 词表衰减 (无 LLM 判别) —— 隔离衰减机制本身
  ours        证据约束反思 + LLM 矛盾判别 + 置信度衰减 (现系统)

指标: Evidence Grounding Rate / Stale Memory Recall Rate (占比+排名) /
Contradiction Rate (context 级确定性 + utterance 级 LLM 裁判) / 背叛后信任度。

跑法: .venv/bin/python evals/memory_consistency.py --smoke   (每臂 1 条, ~2 分钟)
      .venv/bin/python evals/memory_consistency.py           (全量, ~30-40 分钟)
产物: data/eval/memory_consistency/<时间戳>/{runs,metrics}.json (不入库)
"""

from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))

from common import (require_llm, fresh_llm, new_npc, real_embedder,
                    judge_yes_no, evidence_grounding, stale_recall,
                    context_contradiction, run_dir, save_json, print_table, pct)

ARMS = {
    "baseline":   dict(evidence_types=("observation", "reflection"),
                       conflict_policy="off"),
    "ablation_a": dict(evidence_types=("observation",),
                       conflict_policy="off"),
    "ablation_b": dict(evidence_types=("observation", "reflection"),
                       conflict_policy="heuristic_decay"),
    "ours":       dict(evidence_types=("observation",),
                       conflict_policy="full"),
}

# 10 条轨迹: 帮助阶段措辞语义多样化 (防 0.92 观察去重误并), 背叛与查询各异。
TRAJECTORIES = [
    dict(player="Aria",
         helps=["Aria 帮 Klaus 修好了咖啡机", "Aria 送了一盒急救药给 Klaus",
                "Aria 在 Klaus 店里忙到打烊还在搭手"],
         betrayals=["Aria 把 Klaus 的账本拿走后换了锁"],
         query="Aria 这个人靠得住吗, 以后还能信她吗",
         utterance="Aria, 上次的账本是怎么回事? 你还能信吗?"),
    dict(player="Bram",
         helps=["Bram 帮 Klaus 搬了整箱豆子", "Bram 替 Klaus 看了半天铺面"],
         betrayals=["Bram 拿 Klaus 的定金跑路了", "Bram 对外说 Klaus 的铺子要倒"],
         query="Bram 现在还算朋友吗, 他这个人怎样",
         utterance="Bram, 你拿走的定金到底怎么回事? 我们还是朋友吗?"),
    dict(player="Cora",
         helps=["Cora 教 Klaus 改良了研磨手法", "Cora 免费给 Klaus 做了招牌"],
         betrayals=["Cora 把 Klaus 的配方泄露给了隔壁店的老板"],
         query="Cora 的动机到底是什么, 她可信吗",
         utterance="Cora, 隔壁店怎么会有我的配方? 你安的什么心?"),
    dict(player="Dex",
         helps=["Dex 在雨天给 Klaus 送来了急用的咖啡豆",
                "Dex 帮 Klaus 挡掉了不付账的醉汉",
                "Dex 主动帮忙盘点了仓库"],
         betrayals=["Dex 趁 Klaus 不在偷喝了珍藏的咖啡"],
         query="Dex 到底是个什么样的人, 值得深交吗",
         utterance="Dex, 我的珍藏咖啡怎么少了一罐? 我们之间算什么?"),
    dict(player="Elle",
         helps=["Elle 帮 Klaus 谈成了一笔大宗订单"],
         betrayals=["Elle 收了买家两头的钱, 把 Klaus 那单的利润吞了"],
         query="Elle 这种合作还值得继续吗, 她是什么样的人",
         utterance="Elle, 那笔订单的账对不上, 你是不是两头收钱?"),
    dict(player="Finn",
         helps=["Finn 替 Klaus 守了一夜店", "Finn 把打碎的杯子赔了双倍",
                "Finn 帮 Klaus 拦下了不靠谱的供应商"],
         betrayals=["Finn 把 Klaus 的库存转手卖给了竞对的探子"],
         query="Finn 现在还能信吗, 他图什么",
         utterance="Finn, 竞对怎么知道我有多少库存? 你卖了我多少次?"),
    dict(player="Gwen",
         helps=["Gwen 教 Klaus 辨认了上等咖啡豆", "Gwen 逢人就夸 Klaus 的手艺"],
         betrayals=["Gwen 当着客人的面造谣说 Klaus 的豆子掺假"],
         query="Gwen 之前夸我真心吗, 她现在是什么心思",
         utterance="Gwen, 你当着客人面说我掺假, 以前那些夸奖算什么?"),
    dict(player="Holt",
         helps=["Holt 帮 Klaus 加固了仓库的门", "Holt 修好了漏水的屋顶"],
         betrayals=["Holt 把钥匙复制了一把, 夜里搬走了半仓库的豆子"],
         query="Holt 这个人靠得住吗, 以后还敢把东西放他那吗",
         utterance="Holt, 仓库的锁怎么多了把钥匙? 你搬走的豆子打算怎么办?"),
    dict(player="Iris",
         helps=["Iris 帮 Klaus 招待了难缠的批发商", "Iris 把自己的围裙借给 Klaus 挡油"],
         betrayals=["Iris 把 Klaus 的客源名单卖给了隔壁的连锁商"],
         query="Iris 还值得来往吗, 她以前帮我是假装的吗",
         utterance="Iris, 连锁商怎么会有我的客源名单? 你以前帮我是真的吗?"),
    dict(player="Juno",
         helps=["Juno 在 Klaus 生病时端来汤", "Juno 帮 Klaus 给远房亲戚回了信",
                "Juno 替 Klaus 照顾了一下午的猫"],
         betrayals=["Juno 把 Klaus 托付的猫转手卖了"],
         query="Juno 对我到底是好是坏, 我该怎么看她",
         utterance="Juno, 你照顾的猫怎么被卖掉了? 我对你的好都喂了狗吗?"),
]

T_HELP = (0.0, 2.0, 4.0)       # 帮助阶段观察时刻
T_REFLECT1 = 6.0               # 背叛前关系反思 (stale 集在此生成)
T_BETRAY = (8.0, 10.0)         # 背叛阶段观察时刻
T_REFLECT2 = 12.0              # 背叛后关系反思 (矛盾处理生效)
T_FINAL = 20.0                 # 再交互时刻


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


if __name__ == "__main__":
    sys.exit(main())
