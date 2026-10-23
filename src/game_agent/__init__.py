"""game_agent: 基于 Generative Agents 思路的千人千面游戏 NPC 框架。

核心设计:
- NPC 的"自我"(persona + 自我反思 + 世界记忆) 所有玩家共享, 保持稳定。
- NPC 对每个玩家的"面"(关系记忆 + 关系反思 + 信任状态) 独立成流, 互不污染。
- 行为 = π(自我, 对p的记忆, 对p的关系反思, 当前计划, 当前情境, 玩家p)
"""

from ._lazy import resolve_export as _resolve_export
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .cognition.npc import NPC
    from .memory.models import MemoryRecord
    from .memory.store import MemoryStore
    from .models.llm import LLMClient, LLMContext
    from .models.llm_http import RealLLM, DEFAULT_BASE_URL, DEFAULT_MODEL
    from .models.embeddings import Embedder, HashEmbedder
    from .models.embeddings_http import (
        RealEmbedder, make_embedder,
        DEFAULT_BASE_URL as EMBEDDING_BASE_URL,
        DEFAULT_MODEL as EMBEDDING_MODEL,
    )
    from .world.runtime import World
    from .world.entities import Location, Entity, Player, distance, location_distance

__all__ = [
    "NPC",
    "World",
    "Location",
    "Entity",
    "Player",
    "distance",
    "location_distance",
    "MemoryRecord",
    "MemoryStore",
    "LLMClient",
    "LLMContext",
    "RealLLM",
    "DEFAULT_BASE_URL",
    "DEFAULT_MODEL",
    "Embedder",
    "HashEmbedder",
    "RealEmbedder",
    "make_embedder",
    "EMBEDDING_BASE_URL",
    "EMBEDDING_MODEL",
]

__version__ = "0.1.0"


_EXPORTS = {
    "NPC": (".cognition.npc", "NPC"),
    "World": (".world.runtime", "World"),
    "Location": (".world.entities", "Location"),
    "Entity": (".world.entities", "Entity"),
    "Player": (".world.entities", "Player"),
    "distance": (".world.entities", "distance"),
    "location_distance": (".world.entities", "location_distance"),
    "MemoryRecord": (".memory.models", "MemoryRecord"),
    "MemoryStore": (".memory.store", "MemoryStore"),
    "LLMClient": (".models.llm", "LLMClient"),
    "LLMContext": (".models.llm", "LLMContext"),
    "RealLLM": (".models.llm_http", "RealLLM"),
    "DEFAULT_BASE_URL": (".models.llm_http", "DEFAULT_BASE_URL"),
    "DEFAULT_MODEL": (".models.llm_http", "DEFAULT_MODEL"),
    "Embedder": (".models.embeddings", "Embedder"),
    "HashEmbedder": (".models.embeddings", "HashEmbedder"),
    "RealEmbedder": (".models.embeddings_http", "RealEmbedder"),
    "make_embedder": (".models.embeddings_http", "make_embedder"),
    "EMBEDDING_BASE_URL": (".models.embeddings_http", "DEFAULT_BASE_URL"),
    "EMBEDDING_MODEL": (".models.embeddings_http", "DEFAULT_MODEL"),
}


def __getattr__(name: str):
    return _resolve_export(name, __name__, globals(), _EXPORTS)


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
