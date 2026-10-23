"""对话所需的检索、文本补全和回复能力。"""

from __future__ import annotations

from typing import Protocol

from ...models.llm import LLMContext


class DialogueMemory(Protocol):
    def retrieve(self, query: str, now: float, *, top_k: int = 8,
                 player_id: str | None = None,
                 include_player: str | None = None,
                 include_shared: bool = False,
                 min_relevance: float = 0.0) -> list[dict]: ...


class DialogueModel(Protocol):
    def complete(self, ctx: LLMContext) -> str: ...


class DialogueSpeaker(Protocol):
    def reply(self, player_id: str, utterance: str, now: float) -> str: ...
