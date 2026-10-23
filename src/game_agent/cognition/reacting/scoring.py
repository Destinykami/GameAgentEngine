"""事件评分及实例独有的 LRU；缓存键保持事件文本与当前计划。"""

from __future__ import annotations

from collections import OrderedDict

from .contracts import EventModel

EVENT_VALUE_CACHE_LIMIT = 256


class EventScorer:
    def __init__(self, llm: EventModel) -> None:
        self._llm = llm
        self._cache: OrderedDict[
            tuple[str, str], tuple[float, float, float]] = OrderedDict()

    @property
    def cache_size(self) -> int:
        return len(self._cache)

    def score(self, event: str, persona_traits: dict[str, float],
              current_plan: str) -> tuple[float, float, float]:
        """LLM 判断事件价值, 按 (事件, 计划) 缓存。"""
        key = (event, current_plan)
        if key in self._cache:
            self._cache.move_to_end(key)
            return self._cache[key]
        val = self._llm.score_event(event, persona_traits, current_plan)
        self._cache[key] = val
        while len(self._cache) > EVENT_VALUE_CACHE_LIMIT:
            self._cache.popitem(last=False)
        return val

    def clear_cache(self) -> None:
        self._cache.clear()
