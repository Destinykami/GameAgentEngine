"""NPC 暴露的只读记忆视图；不获取世界对象或推进访问时间。"""

from __future__ import annotations

from ...memory.policies import HEARSAY_MAX_HOP
from ...world.social_contracts import Hearsay
from .contracts import MemoryReader, RumorMemory


def rumor_to_share(store: RumorMemory, query: str, now: float) -> Hearsay | None:
    """返回一条相关且尚可传播的传闻，不把记忆存储接口暴露给路由层。"""
    hits = store.retrieve(
        query=query, now=now, top_k=1, types=["observation"],
        hearsay_only=True, min_relevance=0.15, mark_accessed=False)
    if not hits or hits[0]["hop"] >= HEARSAY_MAX_HOP:
        return None
    hit = hits[0]
    return Hearsay(hit["content"], hit["player_id"], hit["hop"])


def decision_context(store: MemoryReader, visible_entities: set[str]) -> str:
    """自治决策只暴露共享记忆与可见对象的关系面，保留原末 5 条窗口。"""
    memories = [m.content for m in store.all_valid()
                if m.player_id is None or m.player_id in visible_entities][-5:]
    return " | ".join(memories)


def identity_belief(store: MemoryReader) -> str:
    """最新有效共享身份信念；是否使用由调用方策略决定。"""
    beliefs = store.all_valid(shared=True, types=["identity"])
    return beliefs[-1].content if beliefs else ""
