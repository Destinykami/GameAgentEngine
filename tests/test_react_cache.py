"""react 决策缓存回归 (F5-2)。

缓存命中必须复用原决策的 react/utility, 不能从 action 文本反解析 —— 事件
文本包含"接受"时, 婉拒串会被误判成接受。
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from persona_agent import NPC
from persona_agent.embeddings import HashEmbedder
from tests.test_persistence import _StubLLM, TRAITS


class _RejectLLM(_StubLLM):
    def score_event(self, event, persona_traits, current_plan=""):
        return (0.0, 0.0, 10.0)   # 效用 -10 → 婉拒


def test_cached_reject_is_not_misread_as_accept():
    npc = NPC("T", dict(TRAITS), llm=_RejectLLM(), embedder=HashEmbedder())
    event = "邀请你接受一场切磋"
    first = npc.react(event, "P", 1.0)
    second = npc.react(event, "P", 2.0)
    assert first.react is False and "婉拒" in first.action
    assert second.react is False, "缓存命中不得把婉拒误读成接受"
    assert second.action == first.action
    assert second.utility == first.utility, "缓存应保留原效用, 不丢成 0"
    assert second.reason == "语义缓存命中"


def test_cached_accept_still_accepts():
    npc = NPC("T", dict(TRAITS), llm=_StubLLM(), embedder=HashEmbedder())
    event = "邀请参加派对"
    first = npc.react(event, "P", 1.0)
    second = npc.react(event, "P", 2.0)
    assert first.react is True
    assert second.react is True and second.action == first.action
    assert second.utility == first.utility
