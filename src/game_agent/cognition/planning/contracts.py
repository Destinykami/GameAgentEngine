"""规划所需的模型和记忆能力，不依赖具体适配器或数据库。"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from ...memory.models import MemoryRecord
from .rules import PlanBlock


class PlanningModel(Protocol):
    def generate_plan(self, persona_traits: dict, previous_day: str, date: str,
                      context: str = "") -> list[PlanBlock]: ...

    def decompose_activity(self, activity: str, start: int,
                           end: int) -> list[PlanBlock]: ...


class PlanningMemory(Protocol):
    def all_valid(self, *, types: Sequence[str] | None = None,
                  shared: bool = False) -> list[MemoryRecord]: ...

    def add(self, rec: MemoryRecord) -> int: ...

    def invalidate(self, mem_id: int) -> None: ...
