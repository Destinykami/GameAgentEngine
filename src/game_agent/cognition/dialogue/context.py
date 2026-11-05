"""单轮对话的记忆可见范围、检索及模型上下文。"""

from __future__ import annotations
import math

from ...models.llm import LLMContext
from ...memory.events import EventScope
from .contracts import DialogueMemory
from .policy import CONTEXT_CHAR_BUDGET, fit_budget, needs_history


# 原始余弦相关性下限，避免无关记忆进入对话；保持原有 0.1 阈值。
RELEVANCE_FLOOR = 0.1


def build_context(store: DialogueMemory, name: str,
                  persona_traits: dict[str, float], player_id: str,
                  utterance: str, now: float, top_k: int = 8) -> LLMContext:
    working = store.working_memories(player_id, now, limit=max(0, top_k))
    history = needs_history(utterance)
    recalled = []
    diagnostics = None
    if history and top_k > 0:
        # 不拿本轮刚收到的提问证明过去；当前事实仍可出现在 working。
        cutoff = math.nextafter(now, -math.inf)
        result = store.hybrid_retrieve(utterance,
            EventScope(as_of=cutoff, player_id=player_id, include_shared=True),
            top_k=min(top_k, 8), candidate_k=32, neighbor_radius=1)
        recalled = [*result.hits, *result.neighbors]
        diagnostics = result.diagnostics
    # 主动追问优先给原文，普通对话只给近期背景；所有内容共同受预算约束。
    memories = fit_budget([*recalled, *working], limit=max(0, top_k) + 4)
    extra = {'memory_mode': 'recall' if history else 'background',
             'memory_budget_chars': CONTEXT_CHAR_BUDGET}
    if diagnostics is not None:
        extra['retrieval'] = diagnostics
    return LLMContext(
        system=(f"你是 {name}。记忆流里出现的 {name} 就是你本人, "
                f"开口时一律用'我', 不要在自己的话里用名字称呼自己。"
                f"人格特质: {persona_traits}。"
                "优先回应眼前的话题。背景记忆用于理解处境和关系，不要主动复述无关旧事或原话。"
                "对过去的具体断言须有历史证据；没有证据时不要编造，仍可正常寒暄和回答当前问题。"),
        player_id=player_id,
        memories=memories,
        question=utterance,
        extra=extra,
    )
