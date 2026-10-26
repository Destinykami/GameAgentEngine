"""独立简化狼人杀示例：规则不依赖空间 World 或 NPC 实现。"""
import random

from .world import DEFAULT_ROLES, WerewolfWorld
from .adapter import WerewolfAdapter


def random_personas(roles, seed=None):
    """为每个席位生成可复现的随机人格，模拟不同玩家。"""
    rng = random.Random(seed)
    return {name: {'social': round(rng.uniform(0.15, 0.9), 2),
                   'goal_oriented': round(rng.uniform(0.15, 0.9), 2)}
            for name in roles}


__all__ = ['DEFAULT_ROLES', 'WerewolfWorld', 'WerewolfAdapter', 'random_personas']
