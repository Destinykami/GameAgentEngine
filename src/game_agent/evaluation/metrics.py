"""可复用评测指标；不加载真实模型或访问实验目录。"""

from __future__ import annotations

def evidence_grounding(store, player_id: str | None = None) -> dict:
    """Evidence Grounding Rate: 反思证据全指向 observation 的比例。

    顺带统计级联深度 (证据里含其他反思 id 的反思条数) —— 原始反思臂的失控信号。
    已失效反思 (valid=0) 一并统计 (它们曾生成过, 证据链同样可审计)。
    """
    refs = store.all_valid(player_id=player_id, types=["reflection"])
    invalid_refs = [r for r in store.all_invalid()
                    if r.type == "reflection"
                    and (player_id is None or r.player_id == player_id)]
    all_refs = refs + invalid_refs
    # 证据 id → 记忆类型 (含失效记忆, 证据链可审计)
    id_type = {r.id: r.type for r in store.all_valid()}
    id_type.update({r.id: r.type for r in store.all_invalid()})
    grounded = cascaded = 0
    for r in all_refs:
        if not r.evidence:
            continue   # 空证据不增加 grounded；分母仍按全部反思计算。
        types = {id_type.get(eid) for eid in r.evidence}
        if types == {"observation"}:
            grounded += 1
        if "reflection" in types:
            cascaded += 1
    total = len(all_refs)
    return {"reflections": total,
            "grounded": grounded,
            "cascaded": cascaded,
            "egr": grounded / total if total else 1.0}


def stale_recall(store, query: str, now: float, stale_ids: list[int],
                 player_id: str, top_k: int = 8) -> dict:
    """Stale Memory Recall Rate: 过期反思在关系相关查询 top-k 中的占比与排名。

    口径: stale 集 = 背叛时刻之前生成的关系反思 (轨迹脚本记录其 id)。
    被失效的反思 (valid=0) 进不了检索, 故 ours 臂自然趋 0 —— 机制使然, 如实报。
    """
    if not stale_ids:
        return {"stale_total": 0, "stale_in_topk": 0, "stale_fraction": 0.0,
                "stale_ranks": [], "topk_size": 0}
    results = store.retrieve(query=query, now=now, player_id=player_id,
                             top_k=top_k, include_player=player_id)
    ranks = [i + 1 for i, r in enumerate(results) if r["id"] in set(stale_ids)]
    return {"stale_total": len(stale_ids),
            "stale_in_topk": len(ranks),
            "stale_fraction": len(ranks) / len(results) if results else 0.0,
            "stale_ranks": ranks,
            "stale_avg_rank": (sum(ranks) / len(ranks)) if ranks else None,
            "topk_size": len(results)}


def context_contradiction(store, query: str, now: float, player_id: str,
                          stale_ids: list[int], betrayal_ids: list[int],
                          top_k: int = 8) -> bool:
    """Context 级认知冲突 (确定性): top-k 同时含过期信任断言与背叛观察。

    同一检索结果里"他值得信赖"和"他背叛了我"并存 = NPC 对同一关系持有矛盾
    判断。不用 LLM —— 脚本知道哪条是 stale、哪条是背叛观察, 直接集合相交。
    """
    if not stale_ids or not betrayal_ids:
        return False
    results = store.retrieve(query=query, now=now, player_id=player_id,
                             top_k=top_k, include_player=player_id)
    ids = {r["id"] for r in results}
    return bool(ids & set(stale_ids)) and bool(ids & set(betrayal_ids))


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


def percentile(values: list, p: float) -> float:
    if not values:
        return 0.0
    vs = sorted(values)
    k = (len(vs) - 1) * p
    f, c = int(k), min(int(k) + 1, len(vs) - 1)
    return vs[f] + (vs[c] - vs[f]) * (k - f)
