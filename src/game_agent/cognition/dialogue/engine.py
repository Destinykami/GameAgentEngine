"""单轮对话生成；对话观察写入及反思门控由 NPC 负责。"""

from __future__ import annotations

from .context import build_context
from .contracts import DialogueMemory, DialogueModel
from .exchange import two_agent_exchange


class DialogueManager:
    def __init__(self, llm: DialogueModel, store: DialogueMemory,
                 persona_traits: dict[str, float], name: str) -> None:
        self._llm = llm
        self._store = store
        self._traits = persona_traits
        self._name = name

    def reply(self, player_id: str, utterance: str, now: float,
              top_k: int = 8) -> str:
        context = build_context(self._store, self._name, self._traits,
                                player_id, utterance, now, top_k)
        return self._llm.complete(context)

    two_agent_exchange = staticmethod(two_agent_exchange)
