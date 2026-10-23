"""增量用量统计，不调用模型或定义重试策略。"""

from typing import Any


def new_stats() -> dict[str, Any]:
    return {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0,
            "total_latency_s": 0.0, "by_method": {}}


def record_stats(stats: dict[str, Any], tag: str, latency_s: float, usage: dict) -> None:
    """记一次 _chat 尝试 (失败也耗了服务端资源, 同样记账; usage 缺失记 0)。"""
    p_tok = int(usage.get("prompt_tokens") or 0)
    c_tok = int(usage.get("completion_tokens") or 0)
    s = stats
    s["calls"] += 1
    s["prompt_tokens"] += p_tok
    s["completion_tokens"] += c_tok
    s["total_latency_s"] += latency_s
    per = s["by_method"].setdefault(tag, {"calls": 0, "prompt_tokens": 0,
                                          "completion_tokens": 0,
                                          "total_latency_s": 0.0})
    per["calls"] += 1
    per["prompt_tokens"] += p_tok
    per["completion_tokens"] += c_tok
    per["total_latency_s"] += latency_s
