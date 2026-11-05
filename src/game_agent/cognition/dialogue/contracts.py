"""对话所需的检索、文本补全和回复能力。"""

from __future__ import annotations

from typing import Protocol

from ...models.llm import LLMContext
from ...memory.events import EventScope
from ...memory.hybrid import HybridResult


class DialogueMemory(Protocol):
    def working_memories(self, player_id: str, now: float, *, limit: int = 8) -> list[dict]: ...

    def hybrid_retrieve(self, query: str, scope: EventScope, *, top_k: int,
                        candidate_k: int, neighbor_radius: int) -> HybridResult: ...


class DialogueModel(Protocol):
    def complete(self, ctx: LLMContext) -> str: ...


class DialogueSpeaker(Protocol):
    def reply(self, player_id: str, utterance: str, now: float) -> str: ...
