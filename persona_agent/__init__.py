"""persona_agent: 基于 Generative Agents 思路的千人千面游戏 NPC 框架。

核心设计:
- NPC 的"自我"(persona + 自我反思 + 世界记忆) 所有玩家共享, 保持稳定。
- NPC 对每个玩家的"面"(关系记忆 + 关系反思 + 信任状态) 独立成流, 互不污染。
- 行为 = π(自我, 对p的记忆, 对p的关系反思, 当前计划, 当前情境, 玩家p)
"""

from .npc import NPC
from .memory import MemoryRecord, MemoryStore
from .llm import LLMClient, LLMContext
from .llm_real import RealLLM, DEFAULT_BASE_URL, DEFAULT_MODEL
from .embeddings import Embedder, HashEmbedder

__all__ = [
    "NPC",
    "MemoryRecord",
    "MemoryStore",
    "LLMClient",
    "LLMContext",
    "RealLLM",
    "DEFAULT_BASE_URL",
    "DEFAULT_MODEL",
    "Embedder",
    "HashEmbedder",
]

__version__ = "0.1.0"
