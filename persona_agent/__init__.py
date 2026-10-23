"""persona_agent: 基于 Generative Agents 思路的千人千面游戏 NPC 框架。

核心设计:
- NPC 的"自我"(persona + 自我反思 + 世界记忆) 所有玩家共享, 保持稳定。
- NPC 对每个玩家的"面"(关系记忆 + 关系反思 + 信任状态) 独立成流, 互不污染。
- 行为 = π(自我, 对p的记忆, 对p的关系反思, 当前计划, 当前情境, 玩家p)
"""

from importlib import import_module as _import_module
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .npc import NPC
    from .memory_model import MemoryRecord
    from .memory import MemoryStore
    from .llm import LLMClient, LLMContext
    from .llm_real import RealLLM, DEFAULT_BASE_URL, DEFAULT_MODEL
    from .embeddings import Embedder, HashEmbedder
    from .embeddings_real import (
        RealEmbedder, make_embedder,
        DEFAULT_BASE_URL as EMBEDDING_BASE_URL,
        DEFAULT_MODEL as EMBEDDING_MODEL,
    )
    from .world import World
    from .world_model import Location, Entity, Player, distance, location_distance

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
    "NPC": (".npc", "NPC"),
    "World": (".world", "World"),
    "Location": (".world_model", "Location"),
    "Entity": (".world_model", "Entity"),
    "Player": (".world_model", "Player"),
    "distance": (".world_model", "distance"),
    "location_distance": (".world_model", "location_distance"),
    "MemoryRecord": (".memory_model", "MemoryRecord"),
    "MemoryStore": (".memory", "MemoryStore"),
    "LLMClient": (".llm", "LLMClient"),
    "LLMContext": (".llm", "LLMContext"),
    "RealLLM": (".llm_real", "RealLLM"),
    "DEFAULT_BASE_URL": (".llm_real", "DEFAULT_BASE_URL"),
    "DEFAULT_MODEL": (".llm_real", "DEFAULT_MODEL"),
    "Embedder": (".embeddings", "Embedder"),
    "HashEmbedder": (".embeddings", "HashEmbedder"),
    "RealEmbedder": (".embeddings_real", "RealEmbedder"),
    "make_embedder": (".embeddings_real", "make_embedder"),
    "EMBEDDING_BASE_URL": (".embeddings_real", "DEFAULT_BASE_URL"),
    "EMBEDDING_MODEL": (".embeddings_real", "DEFAULT_MODEL"),
}


def __getattr__(name: str):
    try:
        module, attribute = _EXPORTS[name]
    except KeyError:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from None
    value = getattr(_import_module(module, __name__), attribute)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
