"""五类记忆的数据契约；不加载数据库、模型或 NPC 运行器。"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import math
from types import MappingProxyType
from typing import TYPE_CHECKING, Mapping

if TYPE_CHECKING:
    from .events import EventRecord
    from .models import MemoryRecord


class MemoryCategory(str, Enum):
    PERSONA_CORE = 'persona_core'
    CURRENT_STATE = 'current_state'
    SEMANTIC = 'semantic'
    EPISODIC = 'episodic'
    RAW_ARCHIVE = 'raw_archive'


def category_for_type(memory_type: str) -> MemoryCategory | None:
    return {
        'plan': MemoryCategory.CURRENT_STATE,
        'reflection': MemoryCategory.SEMANTIC,
        'identity': MemoryCategory.SEMANTIC,
        'observation': MemoryCategory.EPISODIC,
        'episode': MemoryCategory.EPISODIC,
    }.get(memory_type)


def validate_limit(limit: int) -> None:
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 128:
        raise ValueError('每类记忆数量须在 1 到 128 之间')


@dataclass(frozen=True)
class PersonaProfile:
    """显式人设配置；自动反思不能写入，不等同于 identity 信念。"""
    name: str
    traits: Mapping[str, float] = field(default_factory=dict)
    background: str = ''
    values: tuple[str, ...] = ()
    boundaries: tuple[str, ...] = ()
    speech_style: str = ''
    long_term_goals: tuple[str, ...] = ()
    version: int = 1

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError('人格核心必须有 NPC 名称')
        if isinstance(self.version, bool) or not isinstance(self.version, int) or self.version < 1:
            raise ValueError('人格版本必须是正整数')
        traits = dict(self.traits)
        if any(not isinstance(k, str) or not k or isinstance(v, bool)
               or not isinstance(v, (int, float)) or not math.isfinite(v)
               for k, v in traits.items()):
            raise ValueError('人格数值必须为有限数，名称不能为空')
        object.__setattr__(self, 'traits', MappingProxyType(traits))
        for name in ('background', 'speech_style'):
            if not isinstance(getattr(self, name), str):
                raise ValueError(f'{name} 必须是字符串')
        for name in ('values', 'boundaries', 'long_term_goals'):
            value = getattr(self, name)
            if isinstance(value, str):
                raise ValueError(f'{name} 必须是字符串序列')
            value = tuple(value)
            if any(not isinstance(item, str) or not item.strip() for item in value):
                raise ValueError(f'{name} 必须包含非空字符串')
            object.__setattr__(self, name, value)

    def to_dict(self) -> dict:
        return {'name': self.name, 'traits': dict(self.traits),
                'background': self.background, 'values': list(self.values),
                'boundaries': list(self.boundaries), 'speech_style': self.speech_style,
                'long_term_goals': list(self.long_term_goals), 'version': self.version}

    @classmethod
    def from_dict(cls, value: dict) -> PersonaProfile:
        return cls(**value)


@dataclass(frozen=True)
class MemoryContents:
    """存储侧分类结果；原文仅返回事件引用，使用同一范围显式展开。"""
    current_state: tuple[MemoryRecord, ...] = ()
    semantic: tuple[MemoryRecord, ...] = ()
    episodic: tuple[MemoryRecord, ...] = ()
    raw_archive: tuple[EventRecord, ...] = ()


@dataclass(frozen=True)
class CurrentState:
    game_time: float
    tier: str
    plan_blocks: tuple[tuple[int, int, str], ...] = ()
    current_activity: str = ''
    interruption: str = ''
    plan_memories: tuple[MemoryRecord, ...] = ()


@dataclass(frozen=True)
class NPCMemory:
    persona_core: PersonaProfile
    current_state: CurrentState
    semantic: tuple[MemoryRecord, ...] = ()
    episodic: tuple[MemoryRecord, ...] = ()
    raw_archive: tuple[EventRecord, ...] = ()
