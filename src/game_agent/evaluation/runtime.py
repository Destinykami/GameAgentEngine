"""显式在线评测依赖：模型/NPC 工厂、连通性与裁判。导入不请求端点。"""

from __future__ import annotations

import urllib.request

from ..cognition.npc import NPC
from ..models.embeddings_http import make_embedder
from ..models.llm_http import RealLLM, DEFAULT_BASE_URL

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


def new_npc(name: str, traits: dict, llm: RealLLM, embedder, **flags) -> NPC:
    """内存态 NPC (不落库), flags 透传消融开关 (见 EvalPlan.md P1-P4)。"""
    return NPC(name, dict(traits), llm=llm, embedder=embedder, **flags)


def real_embedder():
    """真实 gte-Qwen2 (make_embedder 不可达自动回退 HashEmbedder)。"""
    return make_embedder()


def judge_yes_no(llm: RealLLM, question: str) -> bool:
    """严格 YES/NO 裁判 (同探针模式): 只输出 YES 或 NO, 温度 0。"""
    verdict = llm.ask(question, system="你是一个严格的判断器。只输出 YES 或 NO。",
                      think=False, temperature=0.0, max_tokens=8)
    return verdict.strip().upper().startswith("YES")
