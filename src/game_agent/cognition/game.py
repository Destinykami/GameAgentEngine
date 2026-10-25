"""与空间实体无关的游戏决策上下文；只读取当前实例的个人档案。"""
from dataclasses import dataclass

from ..integration.contracts import DecisionRequest, json_copy
from ..memory.events import EventQuery, EventScope


@dataclass(frozen=True)
class GameDecisionContext:
    request: DecisionRequest
    persona_traits: dict
    memories: tuple[dict, ...]


def build_game_context(store, request: DecisionRequest, persona_traits: dict, *,
                       limit: int = 16, budget: int = 6000) -> GameDecisionContext:
    scope = EventScope(as_of=request.now, instance_id=request.instance_id)
    rows = store.query_events(scope, EventQuery(descending=True), limit=limit).events
    memories = []
    for event in rows:
        if budget <= 0:
            break
        # 私人策略备注不是外界证据，也不混入默认历史窗口。
        if event.event_type == 'private_analysis':
            continue
        source = store.read_event_source(event.source_id, scope)
        if source is None:
            continue
        content = source.content[:min(1000, budget)]
        budget -= len(content)
        memories.append({'source_id': source.id, 'event_type': event.event_type,
            'evidence_kind': event.evidence_kind, 'speaker': event.speaker,
            'now': event.observed_at, 'content': content,
            'truncated': len(content) < len(source.content),
            'channel': source.metadata.get('channel', '')})
    return GameDecisionContext(request, json_copy(persona_traits), tuple(reversed(memories)))
