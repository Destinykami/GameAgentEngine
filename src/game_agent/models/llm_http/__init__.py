"""聊天模型适配器公共入口；任务和传输按需加载。"""

from ..._lazy import resolve_export as _resolve_export

_EXPORTS = {
    "RealLLM": (".client", "RealLLM"),
    "DEFAULT_BASE_URL": ("..config", "DEFAULT_LLM_BASE_URL"),
    "DEFAULT_MODEL": ("..config", "DEFAULT_LLM_MODEL"),
}

__all__ = list(_EXPORTS)


def __getattr__(name: str):
    return _resolve_export(name, __name__, globals(), _EXPORTS)


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
