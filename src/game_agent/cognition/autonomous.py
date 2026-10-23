"""自治决策上下文与模型策略；不负责世界状态修改。"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol

from ..world.entities import Entity


class DecisionCognition(Protocol):
    def has_relationship(self, entity_id: str) -> bool: ...

    def trust_toward(self, entity_id: str) -> float: ...

    def identity_belief(self) -> str: ...


class ActionModel(Protocol):
    def decide_action(self, agent_name: str, goal: str,
                      persona_traits: dict[str, float], perception: str,
                      history: list[str], state: str) -> dict: ...


@dataclass(frozen=True)
class DecisionContext:
    agent_name: str
    goal: str
    persona_traits: dict[str, float]
    visible: tuple[Entity, ...]
    perception: str
    history: list[str]
    state: str


def describe_visible(visible: Iterable[Entity]) -> str:
    descriptions = [f"{other.name}(血{other.health},在{other.location.name})"
                    for other in visible]
    return "; ".join(descriptions) if descriptions else "(空无一人)"


def describe_state(agent: Entity, location_names: Iterable[str]) -> str:
    locs = "/".join(location_names)
    state = (f"血{agent.health}, 攻{agent.attack}, 防{agent.defense}, "
             f"在{agent.location.name} (可选区域: {locs})")
    if agent.reasons:
        state += " | 已积累的理由: " + " / ".join(agent.reasons)
    return state


class AutonomousDecider:
    def decide(self, model: ActionModel, context: DecisionContext, *,
               memory_context: str = "", cognition: DecisionCognition | None = None,
               use_identity_beliefs: bool = False) -> dict:
        perception = context.perception
        if memory_context:
            perception += " | 自己的记忆: " + memory_context
        if cognition is not None:
            trust_bits = [f"{other.name} {cognition.trust_toward(other.name):+.2f}"
                          for other in context.visible
                          if cognition.has_relationship(other.name)]
            if trust_bits:
                perception += " | 对视距内对象的信任度: " + ", ".join(trust_bits)
            if use_identity_beliefs:
                identity = cognition.identity_belief()
                if identity:
                    perception += " | 身份信念: " + identity
        return model.decide_action(context.agent_name, context.goal,
                                   context.persona_traits, perception,
                                   context.history, context.state)
