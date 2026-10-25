"""游戏接入公共契约；不加载世界、NPC、数据库或真实模型。"""
from .contracts import (ActionIntent, ActionSpec, DecisionRequest, GameAdapter,
                        GameEvent, ParameterSpec)
from .session import GameSession

__all__ = ['ActionIntent', 'ActionSpec', 'DecisionRequest', 'GameAdapter',
           'GameEvent', 'ParameterSpec', 'GameSession']
