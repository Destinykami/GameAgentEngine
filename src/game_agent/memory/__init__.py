"""memory 模块公共入口；实现按需加载。"""

from .._lazy import resolve_export as _resolve_export

_EXPORTS = {
    'MemoryStore': ('.store', 'MemoryStore'),
    'MemoryRecord': ('.models', 'MemoryRecord'),
    'ArchiveRecord': ('.archive', 'ArchiveRecord'),
}

__all__ = list(_EXPORTS)


def __getattr__(name: str):
    return _resolve_export(name, __name__, globals(), _EXPORTS)


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
