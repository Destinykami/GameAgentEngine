"""NPC 的完整反应 LRU，与事件评分/信任缓存分别拥有状态。"""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable

from ..reacting.policy import ReactionDecision
from .contracts import ReactionPort

NPC_CACHE_LIMIT = 512


class ReactionCache:
    def __init__(self) -> None:
        self._cache: OrderedDict[tuple, ReactionDecision] = OrderedDict()

    @property
    def size(self) -> int:
        return len(self._cache)

    def clear(self) -> None:
        self._cache.clear()

    def decide(self, decider: ReactionPort, event: str, player_id: str,
               persona_traits: dict[str, float], plan: str,
               can_cache: Callable[[], bool]) -> ReactionDecision:
        if decider.use_relationship:
            trust = decider.relationship_trust(player_id)
        else:
            trust = None
        cache_key = (event, player_id, trust, plan,
                     tuple(sorted(persona_traits.items())), decider.use_relationship)
        cached = self._cache.get(cache_key)
        if cached is not None:
            self._cache.move_to_end(cache_key)   # LRU 命中提权
            # F5-2: 完整复用原决策 (react/action/utility), 只把 reason 换成
            # 缓存命中标记; 不再从 action 文本反解析"接受"。
            return ReactionDecision(react=cached.react, action=cached.action,
                                    utility=cached.utility,
                                    reason="决策缓存命中")
        decision = decider.decide(event, player_id, persona_traits, plan)
        if can_cache():
            self._cache[cache_key] = decision
            self._cache.move_to_end(cache_key)
            while len(self._cache) > NPC_CACHE_LIMIT:
                self._cache.popitem(last=False)
        return decision
