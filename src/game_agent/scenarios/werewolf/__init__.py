"""独立简化狼人杀示例：规则不依赖空间 World 或 NPC 实现。"""
from .world import WerewolfWorld
from .adapter import WerewolfAdapter

__all__ = ['WerewolfWorld', 'WerewolfAdapter']
