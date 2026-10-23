"""事件评分与信任判断各自需要的能力。"""

from __future__ import annotations

from typing import Protocol

from ...memory.models import MemoryRecord


class EventModel(Protocol):
    def score_event(self, event: str, persona_traits: dict[str, float],
                    current_plan: str = "") -> tuple[float, float, float]: ...


class TrustModel(Protocol):
    def judge_trust(self, memories: list[tuple[str, str, float]],
                    player_id: str) -> float: ...


class ReactionModel(EventModel, TrustModel, Protocol):
    pass


class RelationshipMemory(Protocol):
    def all_valid(self, player_id: str) -> list[MemoryRecord]: ...
