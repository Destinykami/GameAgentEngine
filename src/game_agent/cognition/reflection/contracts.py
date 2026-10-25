"""反思所需的模型及记忆能力；不依赖运行时、模型适配或存储实现。"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from ...memory.models import MemoryRecord


class ConflictJudge(Protocol):
    def judge_conflict(self, reflection: str, observation: str) -> int: ...


class ReflectionModel(ConflictJudge, Protocol):
    def reflection_questions(self, recent: Sequence[str]) -> list[str]: ...

    def reflection_insights(self, evidence: list[tuple[int, str]],
                            n: int = 5) -> list[tuple[str, list[int]]]: ...


class ReflectionRecords(Protocol):
    def all_valid(self, player_id: str | None = None, *,
                  types: Sequence[str] | None = None, shared: bool = False,
                  consolidated: bool | None = None) -> list[MemoryRecord]: ...


class ReflectionWriteMemory(ReflectionRecords, Protocol):
    def vectors(self, recs: Sequence[MemoryRecord]) -> list[list[float]]: ...

    def add(self, rec: MemoryRecord) -> int: ...


class ConflictMemory(ReflectionRecords, Protocol):
    def invalidate(self, mem_id: int) -> None: ...

    def update_confidence(self, mem_id: int, confidence: float) -> None: ...


class ReflectionMemory(ReflectionWriteMemory, Protocol):
    def recent_relationship_observations(self, player_id: str, now: float, *,
                                         limit: int = 100) -> list[MemoryRecord]: ...

    def retrieve(self, query: str, now: float, *,
                 player_id: str | None = None, top_k: int = 8,
                 include_player: str | None = None,
                 types: Sequence[str] | None = None,
                 mark_accessed: bool = True, min_relevance: float = 0.0,
                 shared: bool = False,
                 candidate_limit: int | None = None) -> list[dict]: ...
