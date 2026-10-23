"""cognition 模块公共入口；实现按需加载。"""

from .._lazy import resolve_export as _resolve_export

_EXPORTS = {
    'NPC': ('.npc', 'NPC'),
    'ReflectionEngine': ('.reflection', 'ReflectionEngine'),
    'PlanningEngine': ('.planning', 'PlanningEngine'),
    'ReactionDecider': ('.reacting', 'ReactionDecider'),
    'ReactionDecision': ('.reacting', 'ReactionDecision'),
    'DialogueManager': ('.dialogue', 'DialogueManager'),
    'AutonomousDecider': ('.autonomous', 'AutonomousDecider'),
}

__all__ = list(_EXPORTS)


def __getattr__(name: str):
    return _resolve_export(name, __name__, globals(), _EXPORTS)


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
