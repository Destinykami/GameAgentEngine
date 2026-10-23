"""反思模块公共入口，按需加载编排器与规则。"""

from ..._lazy import resolve_export as _resolve_export

__all__ = [
    'ReflectionEngine', 'DEDUP_THRESHOLD', 'CONFLICT_INVALIDATE',
    'CONFLICT_DECAY', 'CONFLICT_RECENT_OBS', 'CONFLICT_DECAY_FLOOR',
    'CONFLICT_CACHE_LIMIT', 'TRUST_WORDS', 'DISTRUST_WORDS',
    'HELP_WORDS', 'HURT_WORDS',
]

_EXPORTS = {
    'ReflectionEngine': ('.engine', 'ReflectionEngine'),
    'DEDUP_THRESHOLD': ('.policies', 'DEDUP_THRESHOLD'),
    'CONFLICT_INVALIDATE': ('.policies', 'CONFLICT_INVALIDATE'),
    'CONFLICT_DECAY': ('.policies', 'CONFLICT_DECAY'),
    'CONFLICT_RECENT_OBS': ('.policies', 'CONFLICT_RECENT_OBS'),
    'CONFLICT_DECAY_FLOOR': ('.policies', 'CONFLICT_DECAY_FLOOR'),
    'CONFLICT_CACHE_LIMIT': ('.policies', 'CONFLICT_CACHE_LIMIT'),
    'TRUST_WORDS': ('.policies', 'TRUST_WORDS'),
    'DISTRUST_WORDS': ('.policies', 'DISTRUST_WORDS'),
    'HELP_WORDS': ('.policies', 'HELP_WORDS'),
    'HURT_WORDS': ('.policies', 'HURT_WORDS'),
}


def __getattr__(name: str):
    return _resolve_export(name, __name__, globals(), _EXPORTS)


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
