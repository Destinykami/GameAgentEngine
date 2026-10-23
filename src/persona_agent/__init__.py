"""旧 persona_agent 导入兼容层；正式实现位于 game_agent。"""

from importlib import import_module as _import_module
import game_agent as _api

__all__ = _api.__all__
__version__ = _api.__version__
_SUBMODULES = ('npc', 'reflection', 'planning', 'reacting', 'dialogue', 'autonomous', 'memory', 'memory_model', 'memory_ranking', 'memory_policy', 'memory_repository', 'world', 'world_model', 'actions', 'perception', 'events', 'world_extensions', 'world_store', 'social', 'social_contracts', 'llm', 'llm_real', 'embeddings', 'embeddings_real', 'probes')


def __getattr__(name: str):
    if name in _SUBMODULES:
        return _import_module(f".{name}", __name__)
    return getattr(_api, name)


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__) | set(_SUBMODULES))
