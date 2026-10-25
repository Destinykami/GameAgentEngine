"""各游戏与 NPC 之间的值契约，禁止传递权威 World 对象。"""
from __future__ import annotations

from dataclasses import dataclass, field
import json
import math
from typing import Any, Protocol


def json_copy(value):
    """断开调用方可变对象；只接受有限的 JSON 值。"""
    return json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False))


def _identifiers(*values):
    if any(not isinstance(value, str) or not value for value in values):
        raise ValueError('标识须为非空字符串')


def _time(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError('时间须为有限数值')


@dataclass(frozen=True)
class ParameterSpec:
    name: str
    value_type: str = 'string'
    description: str = ''
    required: bool = True
    choices: tuple[Any, ...] = ()
    minimum: float | None = None
    maximum: float | None = None
    max_length: int = 2000

    def __post_init__(self):
        _identifiers(self.name)
        if not isinstance(self.description, str):
            raise ValueError('参数说明必须是字符串')
        if self.value_type not in ('string', 'integer', 'number', 'boolean', 'object', 'array'):
            raise ValueError('非法动作参数定义')
        object.__setattr__(self, 'choices', tuple(json_copy(self.choices)))
        if self.max_length < 0:
            raise ValueError('非法长度限制')
        for value in (self.minimum, self.maximum):
            if value is not None and not math.isfinite(value):
                raise ValueError('非法数值范围')
        if self.minimum is not None and self.maximum is not None and self.minimum > self.maximum:
            raise ValueError('非法数值范围')

    def validate(self, value):
        types = {'string': str, 'integer': int, 'number': (int, float),
                 'boolean': bool, 'object': dict, 'array': list}
        if (not isinstance(value, types[self.value_type]) or
                (self.value_type in ('integer', 'number') and isinstance(value, bool))):
            raise ValueError(f'参数 {self.name} 类型不符')
        json_copy(value)
        if self.choices and value not in self.choices:
            raise ValueError(f'参数 {self.name} 不在合法选项中')
        if self.value_type in ('integer', 'number'):
            if ((self.minimum is not None and value < self.minimum) or
                    (self.maximum is not None and value > self.maximum)):
                raise ValueError(f'参数 {self.name} 超出范围')
        elif isinstance(value, (str, dict, list)) and len(value) > self.max_length:
            raise ValueError(f'参数 {self.name} 超出长度')


@dataclass(frozen=True)
class ActionSpec:
    name: str
    description: str = ''
    parameters: tuple[ParameterSpec, ...] = ()

    def __post_init__(self):
        _identifiers(self.name)
        if not isinstance(self.description, str):
            raise ValueError('动作说明必须是字符串')
        object.__setattr__(self, 'parameters', tuple(self.parameters))
        if not self.name or len({p.name for p in self.parameters}) != len(self.parameters):
            raise ValueError('动作名称为空或参数重复')

    def validate(self, arguments: dict) -> None:
        if not isinstance(arguments, dict):
            raise ValueError('动作参数必须是对象')
        known = {p.name for p in self.parameters}
        if set(arguments) - known:
            raise ValueError('动作包含未知参数')
        for p in self.parameters:
            if p.name not in arguments:
                if p.required:
                    raise ValueError(f'缺少动作参数 {p.name}')
            else:
                p.validate(arguments[p.name])


@dataclass(frozen=True)
class DecisionRequest:
    instance_id: str
    request_id: str
    actor_id: str
    state_version: str
    phase: str
    now: float
    goal: str
    view: str
    actions: tuple[ActionSpec, ...]
    instructions: str = ''

    def __post_init__(self):
        object.__setattr__(self, 'actions', tuple(self.actions))
        _identifiers(self.instance_id, self.request_id, self.actor_id, self.state_version, self.phase)
        _time(self.now)
        if any(not isinstance(s, str) for s in (self.goal, self.view, self.instructions)):
            raise ValueError('个人视角、目标和说明必须是字符串，不能传入 World 对象')
        if not self.actions:
            raise ValueError('请求时间或动作集合无效')
        if len({a.name for a in self.actions}) != len(self.actions):
            raise ValueError('动作名称重复')

    def validate(self, intent: ActionIntent) -> None:
        if (intent.instance_id, intent.request_id, intent.actor_id, intent.state_version) != (
                self.instance_id, self.request_id, self.actor_id, self.state_version):
            raise ValueError('行动不属于当前请求或状态已过期')
        spec = next((a for a in self.actions if a.name == intent.action), None)
        if spec is None:
            raise ValueError('当前请求不允许此动作')
        spec.validate(intent.arguments)


@dataclass(frozen=True)
class ActionIntent:
    instance_id: str
    request_id: str
    actor_id: str
    state_version: str
    action: str
    arguments: dict = field(default_factory=dict)
    private_note: str = ''

    def __post_init__(self):
        _identifiers(self.instance_id, self.request_id, self.actor_id, self.state_version, self.action)
        if not isinstance(self.arguments, dict):
            raise ValueError('动作参数必须是对象')
        object.__setattr__(self, 'arguments', json_copy(self.arguments))
        if not isinstance(self.private_note, str):
            raise ValueError('私人备注必须是字符串')


@dataclass(frozen=True)
class GameEvent:
    instance_id: str
    event_id: str
    now: float
    event_type: str
    content: str
    recipients: tuple[str, ...]
    channel: str = 'public'
    actor_id: str | None = None
    participants: tuple[str, ...] = ()
    evidence_kind: str = 'observation'

    def __post_init__(self):
        object.__setattr__(self, 'recipients', tuple(dict.fromkeys(self.recipients)))
        object.__setattr__(self, 'participants', tuple(dict.fromkeys(self.participants)))
        _identifiers(self.instance_id, self.event_id, self.event_type, self.channel,
                     *self.recipients, *self.participants)
        if self.actor_id is not None:
            _identifiers(self.actor_id)
        _time(self.now)
        if not self.recipients:
            raise ValueError('事件缺少实例、标识、类型、频道或接收者')
        if not isinstance(self.content, str) or len(self.content) > 32000:
            raise ValueError('事件时间或内容长度无效')
        if self.evidence_kind not in ('utterance', 'observation', 'report', 'action_attempt',
                                      'derived', 'legacy_snapshot', 'unclassified'):
            raise ValueError('非法事件证据性质')


class GameAdapter(Protocol):
    @property
    def finished(self) -> bool: ...
    def requests(self) -> tuple[DecisionRequest, ...]: ...
    def submit(self, intent: ActionIntent) -> None: ...
    def resolve(self) -> tuple[GameEvent, ...]: ...
    def pending_events(self) -> tuple[GameEvent, ...]: ...
    def ack_event(self, event_id: str) -> None: ...
