"""事件反应编排；完整决策缓存和时钟仍由 NPC 管理。"""

from __future__ import annotations

from .contracts import ReactionModel, RelationshipMemory
from .policy import ReactionDecision, evaluate_response
from .scoring import EventScorer
from .trust import RelationshipTrust


class ReactionDecider:
    def __init__(self, store: RelationshipMemory, llm: ReactionModel,
                 use_relationship: bool = True) -> None:
        self._use_relationship = use_relationship
        self._events = EventScorer(llm)
        self._relationships = RelationshipTrust(store, llm)

    @property
    def use_relationship(self) -> bool:
        return self._use_relationship

    def relationship_trust(self, player_id: str | None) -> float:
        return self._relationships.get(player_id)

    def decide(self, event: str, player_id: str,
               persona_traits: dict[str, float],
               current_plan: str = "") -> ReactionDecision:
        # 先解包评分，再查信任：保留无效模型返回时的失败顺序。
        v_social, v_goal, c_interrupt = self._events.score(
            event, persona_traits, current_plan)
        enabled = bool(self._use_relationship)
        trust = self.relationship_trust(player_id) if enabled else 0.0
        return evaluate_response(event, persona_traits,
                                 (v_social, v_goal, c_interrupt), trust,
                                 use_relationship=enabled)

    def clear_cache(self) -> None:
        self._events.clear_cache()
        self._relationships.clear_cache()

    def cache_sizes(self) -> dict[str, int]:
        return {"events": self._events.cache_size,
                "trust": self._relationships.cache_size}
