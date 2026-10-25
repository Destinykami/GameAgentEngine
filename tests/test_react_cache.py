"""react 决策缓存回归 (F5-2)。

缓存命中必须复用原决策的 react/utility, 不能从 action 文本反解析 —— 事件
文本包含"接受"时, 婉拒串会被误判成接受。
"""

from __future__ import annotations



from game_agent import NPC
from game_agent.models.embeddings import HashEmbedder
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
    assert second.reason == "决策缓存命中"


def test_cached_accept_still_accepts():
    npc = NPC("T", dict(TRAITS), llm=_StubLLM(), embedder=HashEmbedder())
    event = "邀请参加派对"
    first = npc.react(event, "P", 1.0)
    second = npc.react(event, "P", 2.0)
    assert first.react is True
    assert second.react is True and second.action == first.action
    assert second.utility == first.utility


def test_source_upgrade_recomputes_utility_within_old_trust_bucket():
    class Model(_StubLLM):
        calls = 0
        def judge_trust(self, memories, player_id):
            self.calls += 1
            return 0.1 if '[传闻' in memories[0][1] else 0.2
        def score_event(self, *args):
            return (10, 0, 11.5)
    model = Model()
    npc = NPC('T', {'social': 1}, llm=model)
    try:
        npc.observe('P 帮我修好了咖啡机', 0, 'P', hearsay=True, hop=2)
        first = npc.react('邀请', 'P', 1)
        npc.observe('P 帮我修好了咖啡机', 2, 'P')
        second = npc.react('邀请', 'P', 3)
        assert not first.react and second.react
        assert abs(second.utility - 0.5) < 1e-9
        assert model.calls == 2
        assert npc.react('邀请', 'P', 4).reason == '决策缓存命中'
        assert model.calls == 2
    finally:
        npc.store.close()


def test_persona_mutation_refreshes_both_decision_and_event_score():
    class Model(_StubLLM):
        calls = 0
        def score_event(self, event, traits, current_plan=''):
            self.calls += 1
            return (traits['social'] * 10, 0, 3)
    model = Model()
    npc = NPC('T', {'social': 0.1}, llm=model)
    try:
        assert not npc.react('邀请', 'P', 0).react
        npc.persona_traits['social'] = 1
        assert npc.react('邀请', 'P', 1).react
        assert model.calls == 2
    finally:
        npc.store.close()
