"""NPC 编排公共入口；实现按需加载。"""

from ..._lazy import resolve_export as _resolve_export

_EXPORTS = {
    "NPC": (".engine", "NPC"),
    "REFLECTION_THRESHOLD": (".state", "REFLECTION_THRESHOLD"),
    "SWEEP_INTERVAL": (".state", "SWEEP_INTERVAL"),
    "NPC_CACHE_LIMIT": (".reactions", "NPC_CACHE_LIMIT"),
}

__all__ = list(_EXPORTS)


def __getattr__(name: str):
    return _resolve_export(name, __name__, globals(), _EXPORTS)


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
