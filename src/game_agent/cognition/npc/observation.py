"""观察写入与动作描述；时钟、档位和反思累积由编排器管理。"""

from __future__ import annotations

from dataclasses import dataclass

from ...memory.models import MemoryRecord
from .contracts import ImportanceModel, MemoryReader, ObservationMemory, PerceptionModel


@dataclass(frozen=True)
class ObservationResult:
    memory_id: int
    created: bool
    importance: float | None = None


def write_observation(store: ObservationMemory, model: ImportanceModel,
                      content: str, now: float, player_id: str | None = None,
                      hearsay: bool = False, hop: int = 0,
                      importance: float | None = None) -> ObservationResult:
    # 查重先于评分；重复观察不消耗评分调用，也不驱动反思累积。
    dup = store.find_similar_observation(content, player_id)
    if dup is not None:
        store.merge_observation(dup.id, now, new_hearsay=hearsay,
                                new_hop=hop, new_content=content)
        return ObservationResult(dup.id, False)
    if importance is None:
        importance = model.score_importance(content, player_id)
    rec = MemoryRecord(content=content, timestamp=now, type="observation",
                       player_id=player_id, importance=importance,
                       hearsay=hearsay, hop=hop)
    mem_id = store.add(rec)
    return ObservationResult(mem_id, True, importance)


def describe_action(store: MemoryReader, model: PerceptionModel,
                     npc_name: str, player_name: str, action: str) -> str:
    recent = [m.content for m in store.all_valid(
        player_id=player_name, types=["observation"])[-3:]]
    context = " | ".join(recent) if recent else ""
    return model.perceive_action(npc_name, player_name, action, context)
