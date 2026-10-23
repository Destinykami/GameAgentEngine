"""单轮对话的记忆可见范围、检索及模型上下文。"""

from __future__ import annotations

from ...models.llm import LLMContext
from .contracts import DialogueMemory


# 原始余弦相关性下限，避免无关记忆进入对话；保持原有 0.1 阈值。
RELEVANCE_FLOOR = 0.1


def build_context(store: DialogueMemory, name: str,
                  persona_traits: dict[str, float], player_id: str,
                  utterance: str, now: float, top_k: int = 8) -> LLMContext:
    query = f"{utterance} (对话者: {player_id})"
    # 当前对话者的关系面 + 共享流。沿用 mark_accessed=True 默认值，
    # 检索是实际回忆，即使后续模型生成失败也不回滚访问时间。
    memories = store.retrieve(
        query=query, now=now, top_k=top_k, player_id=player_id,
        include_player=player_id, include_shared=True,
        min_relevance=RELEVANCE_FLOOR)
    return LLMContext(
        system=(f"你是 {name}。记忆流里出现的 {name} 就是你本人, "
                f"开口时一律用'我', 不要在自己的话里用名字称呼自己。"
                f"只基于你记得的事情回答。人格特质: {persona_traits}"),
        player_id=player_id,
        memories=memories,
        question=utterance,
    )
