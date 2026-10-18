"""use_relationship 消融开关回归 (F5-4)。

关闭时反应决策彻底不计算 trust (零 judge_trust 调用), 缓存键也不带 trust
维度; 开启时恢复信任调制。
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from persona_agent import NPC
from persona_agent.embeddings import HashEmbedder
from tests.test_persistence import _StubLLM, TRAITS


class _CountingTrust(_StubLLM):
    def __init__(self) -> None:
        super().__init__()
        self.trust_calls = 0

    def judge_trust(self, memories, player_id):
        self.trust_calls += 1
        return super().judge_trust(memories, player_id)


def _npc(use_relationship: bool) -> tuple[NPC, _CountingTrust]:
    llm = _CountingTrust()
    npc = NPC("T", dict(TRAITS), llm=llm, embedder=HashEmbedder(),
              use_relationship=use_relationship)
    npc.observe("P 帮过我", 1.0, player_id="P")
    npc.observe("Q 骗过我", 1.0, player_id="Q")
    return npc, llm


def test_disabled_ablation_skips_trust_entirely():
    npc, llm = _npc(use_relationship=False)
    npc.react("邀请参加派对", "P", 2.0)
    npc.react("邀请参加派对", "Q", 2.0)
    assert llm.trust_calls == 0, "关闭关系调制时不应调用 judge_trust"


def test_enabled_ablation_still_uses_trust():
    npc, llm = _npc(use_relationship=True)
    npc.react("邀请参加派对", "P", 2.0)
    npc.react("邀请参加派对", "Q", 2.0)
    assert llm.trust_calls >= 2


def test_disabled_ablation_actions_do_not_depend_on_trust():
    npc, _llm = _npc(use_relationship=False)
    p = npc.react("邀请参加派对", "P", 2.0)
    q = npc.react("邀请参加派对", "Q", 2.0)
    assert p.action == q.action
