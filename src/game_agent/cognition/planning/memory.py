"""计划记忆契约：上下文读取、逐条写入和旧计划失效。"""

from __future__ import annotations

from collections.abc import Sequence

from ...memory.models import MemoryRecord
from .contracts import PlanningMemory


def save_plan(store: PlanningMemory, now: float, content: str,
              player_id: str | None) -> int:
    return store.add(MemoryRecord(content=content, timestamp=now,
                                  type="plan", player_id=player_id,
                                  importance=4.0))


def save_observation(store: PlanningMemory, now: float, content: str,
                     player_id: str | None = None) -> int:
    return store.add(MemoryRecord(content=content, timestamp=now,
                                  type="observation", player_id=player_id,
                                  importance=5.0))


def active_plan_ids(store: PlanningMemory) -> list[int]:
    return [record.id for record in store.all_valid(types=["plan"])]


def retire_plans(store: PlanningMemory, ids: Sequence[int]) -> None:
    for old_id in ids:
        store.invalidate(old_id)


def previous_day_context(store: PlanningMemory, fallback: str) -> str:
    plans = store.all_valid(types=["plan"])
    if plans:
        return "前一天活动: " + " | ".join(plan.content for plan in plans)
    return fallback


def shared_world_context(store: PlanningMemory) -> str:
    recent = [record.content for record in store.all_valid(
        shared=True, types=["observation"])[-10:]]
    return " | ".join(recent) if recent else ""
