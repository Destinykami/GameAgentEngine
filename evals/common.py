"""evals/common.py — 三实验共用件: NPC 工厂、LLM 裁判、指标计算、结果落盘。

依赖方向: evals → persona_agent (单向)。本模块只通过公开 API 观察系统,
不 monkeypatch、不改游戏路径行为。裁判用 LLM 时 temperature=0 (同探针)。
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from persona_agent import NPC, make_embedder
from persona_agent.llm_real import RealLLM, DEFAULT_BASE_URL

DATA_ROOT = os.path.join(os.path.dirname(__file__), "..", "data", "eval")


# ---------------------------------------------------------------- 连通性
def llm_available(base_url: str = DEFAULT_BASE_URL, timeout: float = 6.0) -> bool:
    """轻量连通性检查 (GET /v1/models)。不可达时实验脚本应 fail fast。"""
    try:
        with urllib.request.urlopen(base_url.rstrip("/") + "/v1/models",
                                    timeout=timeout) as r:
            return r.status == 200
    except Exception:
        return False


def require_llm(base_url: str = DEFAULT_BASE_URL) -> RealLLM:
    """构造 RealLLM; 端点不可达直接抛错 (实验硬依赖, 不 skip)。"""
    if not llm_available(base_url):
        raise RuntimeError(f"LLM 端点不可达: {base_url} — 实验需要真实 LLM")
    return RealLLM(base_url=base_url)


def fresh_llm(base_url: str = DEFAULT_BASE_URL) -> RealLLM:
    """独立 RealLLM 实例 (每 NPC 一个, usage 计数器天然 per-NPC 归属)。"""
    return RealLLM(base_url=base_url)


# ---------------------------------------------------------------- NPC 工厂
def new_npc(name: str, traits: dict, llm: RealLLM, embedder, **flags) -> NPC:
    """内存态 NPC (不落库), flags 透传消融开关 (见 EvalPlan.md P1-P4)。"""
    return NPC(name, dict(traits), llm=llm, embedder=embedder, **flags)


def real_embedder():
    """真实 gte-Qwen2 (make_embedder 不可达自动回退 HashEmbedder)。"""
    return make_embedder()


# ---------------------------------------------------------------- LLM 裁判
def judge_yes_no(llm: RealLLM, question: str) -> bool:
    """严格 YES/NO 裁判 (同探针模式): 只输出 YES 或 NO, 温度 0。"""
    verdict = llm.ask(question, system="你是一个严格的判断器。只输出 YES 或 NO。",
                      think=False, temperature=0.0, max_tokens=8)
    return verdict.strip().upper().startswith("YES")


# ---------------------------------------------------------------- 记忆指标
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
            continue   # 无证据引用的反思不计入分母 (兜底引用在生成层已保证)
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


# ---------------------------------------------------------------- 结果落盘
def run_dir(exp_name: str) -> str:
    """每次跑批的产物目录: data/eval/<exp>/<时间戳>/ (被 .gitignore 挡住)。"""
    d = os.path.join(DATA_ROOT, exp_name, time.strftime("%Y%m%d-%H%M%S"))
    os.makedirs(d, exist_ok=True)
    return d


def save_json(path: str, obj) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2, default=str)


def load_json(path: str):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def print_table(headers: list[str], rows: list[list]) -> None:
    """朴素对齐表格 (标准库, 无依赖)。"""
    widths = [max(len(str(h)), *(len(str(r[i])) for r in rows)) if rows
              else len(str(h))
              for i, h in enumerate(headers)]
    line = "  ".join(str(h).ljust(widths[i]) for i, h in enumerate(headers))
    print(line)
    print("-" * len(line))
    for r in rows:
        print("  ".join(str(c).ljust(widths[i]) for i, c in enumerate(r)))


def pct(x: float) -> str:
    return f"{x * 100:.1f}%"
