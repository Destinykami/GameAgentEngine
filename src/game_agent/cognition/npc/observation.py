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
                      importance: float | None = None, *,
                      source_id: str | None = None) -> ObservationResult:
    if source_id is None:
        source_id = archive_observation(store, content, now, player_id,
                                        hearsay=hearsay, hop=hop, importance=importance)
    existing = store.projected_id(source_id)
    if existing is not None:
        store.archive_done(source_id)
        return ObservationResult(existing, False)
    try:
        return _project_observation(store, model, content, now, player_id,
                                    hearsay, hop, importance, source_id)
    except Exception as exc:
        store.archive_failed(source_id, exc)
        raise


def archive_observation(store: ObservationMemory, content: str, now: float,
                        player_id: str | None = None, *, hearsay: bool = False,
                        hop: int = 0, importance: float | None = None,
                        raw_content: str | None = None, kind: str = 'observation',
                        speaker: str | None = None, session_id: str = '') -> str:
    return store.archive_input(content if raw_content is None else raw_content, now,
        player_id, kind=kind, speaker=speaker, session_id=session_id,
        hearsay=hearsay, hop=hop,
        metadata={'projection': 'observation', 'content': content, 'importance': importance})


def _project_observation(store, model, content, now, player_id, hearsay, hop,
                         importance, source_id) -> ObservationResult:
    # 查重先于评分；重复观察不消耗评分调用，也不驱动反思累积。
    dup = store.find_similar_observation(content, player_id)
    if dup is not None:
        store.merge_observation(dup.id, now, new_hearsay=hearsay,
                                new_hop=hop, new_content=content, source_id=source_id)
        store.archive_done(source_id)
        return ObservationResult(dup.id, False)
    if importance is None:
        importance = model.score_importance(content, player_id)
    rec = MemoryRecord(content=content, timestamp=now, type="observation",
                       player_id=player_id, importance=importance,
                       hearsay=hearsay, hop=hop)
    mem_id = store.add(rec, source_id=source_id)
    return ObservationResult(mem_id, True, importance)


def describe_action(store: MemoryReader, model: PerceptionModel,
                     npc_name: str, player_name: str, action: str) -> str:
    recent = [m.content for m in store.all_valid(
        player_id=player_name, types=["observation"])[-3:]]
    context = " | ".join(recent) if recent else ""
    return model.perceive_action(npc_name, player_name, action, context)
