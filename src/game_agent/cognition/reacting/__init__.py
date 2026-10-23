"""事件反应与关系信任的公共入口；实现按需加载。"""

from ..._lazy import resolve_export as _resolve_export

_EXPORTS = {
    "ReactionDecider": (".engine", "ReactionDecider"),
    "ReactionDecision": (".policy", "ReactionDecision"),
    "JUDGE_TRUST_MAX_MEMORIES": (".trust", "JUDGE_TRUST_MAX_MEMORIES"),
    "EVENT_VALUE_CACHE_LIMIT": (".scoring", "EVENT_VALUE_CACHE_LIMIT"),
}

__all__ = list(_EXPORTS)


def __getattr__(name: str):
    return _resolve_export(name, __name__, globals(), _EXPORTS)


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
