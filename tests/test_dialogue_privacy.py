"""对话检索的面隔离回归 (F1-4)。

对话候选集 = 当前对话者的关系面 + 共享流。别的玩家的私有记忆不得进入 prompt,
否则 NPC 会把 A 的秘密说给 B; 共享世界事件仍应可见。
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from persona_agent import NPC
from persona_agent.embeddings import HashEmbedder
from tests.test_persistence import _StubLLM, TRAITS


class _CaptureComplete(_StubLLM):
    def __init__(self) -> None:
        super().__init__()
        self.contexts = []

    def complete(self, ctx):
        self.contexts.append(ctx)
        return super().complete(ctx)


def _npc() -> tuple[NPC, _CaptureComplete]:
    llm = _CaptureComplete()
    npc = NPC("测试人", dict(TRAITS), llm=llm, embedder=HashEmbedder())
    npc.observe("Aria 悄悄告诉我: 她把神之眼藏在神樱树下", 1.0,
                player_id="Aria")
    npc.observe("Bram 问我知不知道藏眼神的事", 2.0, player_id="Bram")
    npc.observe("城里开始收缴神之眼", 3.0)   # 共享流
    return npc, llm


def _contents(ctx) -> str:
    return " | ".join(m["content"] for m in ctx.memories)


def test_dialogue_to_other_player_excludes_private_memory():
    npc, llm = _npc()
    npc.speak("Bram", "神之眼藏在哪里?", 4.0)
    ctx = llm.contexts[-1]
    text = _contents(ctx)
    assert "神樱树下" not in text, "Aria 的私有秘密不得进入与 Bram 的对话"
    assert all(m["player_id"] in (None, "Bram") for m in ctx.memories), \
        "对话候选集只能是当前玩家 + 共享流"
    assert "城里开始收缴神之眼" in text, "共享世界事件仍应可见"


def test_dialogue_to_owner_includes_own_private_memory():
    npc, llm = _npc()
    npc.speak("Aria", "神之眼藏在哪里?", 4.0)
    ctx = llm.contexts[-1]
    text = _contents(ctx)
    assert "神樱树下" in text, "与 Aria 本人对话应能召回她自己的记忆"
    assert all(m["player_id"] in (None, "Aria") for m in ctx.memories)
