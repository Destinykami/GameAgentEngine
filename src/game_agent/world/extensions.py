"""动作效果注册与行为链计数；世界事件由调用方广播。"""

from __future__ import annotations

from collections.abc import Callable

from .events import VisualEvent
from .entities import Entity

ActionEffect = Callable[[object, Entity, Entity | None, dict, VisualEvent], None]


class WorldExtensions:
    def __init__(self) -> None:
        self.action_effects: dict[str, list[ActionEffect]] = {}
        self._chain_rules: dict[str, tuple[int, str]] = {}
        self._chain_counters: dict[str, dict[tuple[str, str], int]] = {}

    def add_action_effect(self, action: str, fn: ActionEffect) -> None:
        self.action_effects.setdefault(action, []).append(fn)

    def run_effects(self, context: object, action: str, actor: Entity,
                    target: Entity | None, action_dict: dict,
                    event: VisualEvent) -> None:
        for effect in self.action_effects.get(action, []):
            effect(context, actor, target, action_dict, event)

    def add_chain_rule(self, action: str, threshold: int, description: str) -> None:
        self._chain_rules[action] = (threshold, description)

    def record_action(self, actor_id: str, action: str,
                      target_id: str) -> str | None:
        key = (action, target_id)
        counters = self._chain_counters.get(actor_id)
        if counters:
            for other in [k for k in counters if k != key]:
                del counters[other]
        rule = self._chain_rules.get(action)
        if rule is None:
            return None
        threshold, description = rule
        if counters is None:
            counters = self._chain_counters[actor_id] = {}
        counters[key] = counters.get(key, 0) + 1
        if counters[key] >= threshold:
            counters[key] = 0
            return description
        return None

    def checkpoint_state(self) -> dict:
        return {"rules": {key: list(rule) for key, rule in self._chain_rules.items()},
                "counters": {actor: [[action, target, count] for (action, target), count in counts.items()]
                             for actor, counts in self._chain_counters.items()},
                "effects": {action: len(effects) for action, effects in self.action_effects.items()}}

    def restore_checkpoint(self, state: dict) -> None:
        self._chain_rules = {action: tuple(rule) for action, rule in state["rules"].items()}
        self._chain_counters = {actor: {(action, target): count for action, target, count in rows}
                                for actor, rows in state["counters"].items()}

    def validate_bindings(self, state: dict) -> None:
        actual = {action: len(effects) for action, effects in self.action_effects.items()}
        if actual != state["effects"]:
            raise ValueError("检查点动作效果必须由 configure 完整重绑定")
