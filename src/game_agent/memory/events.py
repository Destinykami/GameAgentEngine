"""通用历史查询的轻量契约；不依赖数据库、世界或模型。"""
from __future__ import annotations

from dataclasses import dataclass
import math


EVIDENCE_KINDS = frozenset({
    'utterance', 'observation', 'report', 'action_attempt', 'derived',
    'legacy_snapshot', 'unclassified',
})


def _finite(name: str, value: float | None) -> None:
    if value is not None and (isinstance(value, bool) or not math.isfinite(value)):
        raise ValueError(f'{name} 必须是有限游戏时间')


@dataclass(frozen=True)
class EventContext:
    event_type: str | None = None
    occurred_at: float | None = None
    actor: str | None = None
    target: str | None = None
    participants: tuple[str, ...] = ()
    location: str | None = None
    evidence_kind: str | None = None

    def __post_init__(self) -> None:
        _finite('occurred_at', self.occurred_at)
        if self.evidence_kind is not None and self.evidence_kind not in EVIDENCE_KINDS:
            raise ValueError('不支持的证据性质')
        object.__setattr__(self, 'participants', tuple(dict.fromkeys(self.participants)))
        if len(self.participants) > 64 or any(not p for p in self.participants):
            raise ValueError('参与者须非空且不超过 64 个')


@dataclass(frozen=True, kw_only=True)
class EventScope:
    as_of: float
    player_id: str | None = None
    include_shared: bool = False

    def __post_init__(self) -> None:
        if self.as_of is None:
            raise ValueError('必须指定查询时间上界')
        _finite('as_of', self.as_of)


@dataclass(frozen=True)
class EventQuery:
    event_types: tuple[str, ...] = ()
    evidence_kinds: tuple[str, ...] = ()
    actor: str | None = None
    target: str | None = None
    speaker: str | None = None
    participants: tuple[str, ...] = ()  # 同时包含所有指定参与者
    location: str | None = None
    session_id: str | None = None
    text: str = ''  # 词项 OR 匹配，不是语义判定或任意 FTS/SQL 表达式
    occurred_after: float | None = None
    occurred_before: float | None = None
    observed_after: float | None = None
    observed_before: float | None = None
    after_event: str | None = None  # 按档案追加顺序的严格锚点
    before_event: str | None = None
    order_by: str = 'sequence'
    descending: bool = False

    def __post_init__(self) -> None:
        for name in ('event_types', 'evidence_kinds', 'participants'):
            value = tuple(dict.fromkeys(getattr(self, name)))
            if len(value) > 64:
                raise ValueError(f'{name} 最多 64 项')
            object.__setattr__(self, name, value)
        if not set(self.evidence_kinds) <= EVIDENCE_KINDS:
            raise ValueError('不支持的证据性质')
        if self.order_by not in ('sequence', 'occurred_at', 'observed_at'):
            raise ValueError('不支持的事件排序')
        if len(self.text) > 4000:
            raise ValueError('查询文本最多 4000 字符')
        for prefix in ('occurred', 'observed'):
            lower, upper = getattr(self, prefix + '_after'), getattr(self, prefix + '_before')
            _finite(prefix + '_after', lower)
            _finite(prefix + '_before', upper)
            if lower is not None and upper is not None and lower > upper:
                raise ValueError('查询时间范围倒置')


@dataclass(frozen=True)
class EventRecord:
    source_id: str
    sequence: int
    event_type: str
    occurred_at: float | None
    observed_at: float | None
    actor: str | None
    target: str | None
    participants: tuple[str, ...]
    location: str | None
    evidence_kind: str
    kind: str
    speaker: str | None
    player_id: str | None
    session_id: str
    hearsay: bool
    hop: int


@dataclass(frozen=True)
class EventCursor:
    archive_id: str
    fingerprint: str
    high_water: int
    sort_value: float | int
    sequence: int


@dataclass(frozen=True)
class EventPage:
    events: tuple[EventRecord, ...]
    next_cursor: EventCursor | None = None
