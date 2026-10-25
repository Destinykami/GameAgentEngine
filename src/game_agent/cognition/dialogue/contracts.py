"""对话所需的检索、文本补全和回复能力。"""

from __future__ import annotations

from typing import Protocol

from ...models.llm import LLMContext


class DialogueMemory(Protocol):
    def working_memories(self, player_id: str, now: float, *, limit: int = 8) -> list[dict]: ...

    def retrieve_important(self, query: str, now: float, player_id: str, *,
                           top_k: int = 4) -> list[dict]: ...

    def search_archive(self, query: str, *, player_id: str,
                       include_shared: bool, before: float, limit: int) -> list[dict]: ...

    def archive_neighbors(self, source_id: str, *, player_id: str,
                          include_shared: bool, before: float, radius: int) -> list: ...


class DialogueModel(Protocol):
    def complete(self, ctx: LLMContext) -> str: ...


class DialogueSpeaker(Protocol):
    def reply(self, player_id: str, utterance: str, now: float) -> str: ...
