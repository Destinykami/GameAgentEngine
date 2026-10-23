"""NPC 子组件的窄端口，不依赖 NPC、World、SQLite 或模型适配器。"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any, Protocol

from ...memory.models import MemoryRecord
from ..reacting.policy import ReactionDecision


class ImportanceModel(Protocol):
    def score_importance(self, text: str, player_id: str | None = None) -> float: ...


class PerceptionModel(Protocol):
    def perceive_action(self, npc_name: str, player_name: str, action: str,
                        context: str = "") -> str: ...


class MemoryReader(Protocol):
    def all_valid(self, player_id: str | None = None,
                  types: Sequence[str] | None = None, *, shared: bool = False,
                  consolidated: bool | None = None) -> list[MemoryRecord]: ...


class ObservationMemory(Protocol):
    def find_similar_observation(self, content: str,
                                 player_id: str | None = None) -> MemoryRecord | None: ...

    def merge_observation(self, mem_id: int, now: float, *,
                          new_hearsay: bool | None = None, new_hop: int = 0,
                          new_content: str | None = None) -> float: ...

    def add(self, rec: MemoryRecord) -> int: ...


class ConsolidationModel(Protocol):
    def consolidate_observations(self, observations: list[str],
                                  player_id: str | None = None) -> str: ...


class ConsolidationMemory(MemoryReader, Protocol):
    def add(self, rec: MemoryRecord) -> int: ...

    def mark_consolidated(self, mem_ids: Iterable[int]) -> int: ...


class RumorMemory(Protocol):
    def retrieve(self, query: str, now: float, *, top_k: int,
                 types: Sequence[str], hearsay_only: bool,
                 min_relevance: float, mark_accessed: bool) -> list[dict[str, Any]]: ...


class MetadataMemory(Protocol):
    def is_persistent(self) -> bool: ...

    def get_meta(self, key: str, default: Any = None) -> Any: ...

    def set_meta(self, key: str, value: Any) -> None: ...

    def db_path(self) -> str: ...


class ReactionPort(Protocol):
    @property
    def use_relationship(self) -> bool: ...

    def relationship_trust(self, player_id: str) -> float: ...

    def decide(self, event: str, player_id: str, persona_traits: dict[str, float],
               current_plan: str = "") -> ReactionDecision: ...
