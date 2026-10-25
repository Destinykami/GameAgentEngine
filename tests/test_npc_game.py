"""通用 NPC 只使用授权个人视角、本实例记忆和动态动作。"""
from dataclasses import replace

import pytest

from game_agent import NPC
from game_agent.integration import ActionIntent, ActionSpec, DecisionRequest, GameEvent, ParameterSpec
from game_agent.memory import EventScope
from tests.test_persistence import _StubLLM


class Model(_StubLLM):
    def decide_game(self, context):
        self.context = context
        r = context.request
        return ActionIntent(r.instance_id, r.request_id, r.actor_id, r.state_version,
                            'vote', {'target': 'B'}, private_note='私人策略')


def request():
    return DecisionRequest('match', 'r1', 'A', 'v1', 'vote', 10, '阵营取胜', '公开局势',
        (ActionSpec('vote', parameters=(ParameterSpec('target', choices=('B', 'C')),)),))


def event(event_id='e1', **kwargs):
    return GameEvent('match', event_id, 1, 'claim', '  B 声称自己是预言家\n', ('A',),
                      actor_id='B', evidence_kind='utterance', **kwargs)


def test_authorized_raw_delivery_is_idempotent_and_separate_from_old_chat():
    npc = NPC('A', {}, Model())
    try:
        first = npc.receive_game_event(event())
        assert npc.receive_game_event(event()) == first
        assert npc.store.archive_count() == 1 and npc.memory_count() == 0
        assert npc.store.pending_archive() == []
        assert npc.store.search_archive('预言家') == []
        with pytest.raises(PermissionError):
            npc.receive_game_event(replace(event(), recipients=('B',)))
        raw = npc.store.read_event_source(first, EventScope(as_of=2, instance_id='match'))
        assert raw.content == '  B 声称自己是预言家\n'
        with pytest.raises(Exception, match='不一致'):
            npc.receive_game_event(replace(event(), content='改写后的原话'))
    finally:
        npc.store.close()


def test_context_excludes_other_instances_future_and_private_analysis_and_keeps_persona():
    model = Model()
    npc = NPC('A', {'social': .7}, model)
    try:
        npc.observe('旧世界的隐私', 1)
        npc.receive_game_event(event())
        npc.receive_game_event(replace(event('other'), instance_id='other', content='另一局真相'))
        npc.receive_game_event(replace(event('future'), now=100, content='未来事实'))
        npc.receive_game_event(replace(event('private'), event_type='private_analysis', content='私人推测'))
        action = npc.decide_game(request())
        assert action.arguments == {'target': 'B'}
        assert [m['content'] for m in model.context.memories] == [event().content]
        assert model.context.persona_traits == {'social': .7}
        model.context.persona_traits['social'] = 0
        assert npc.persona_traits['social'] == .7
        with pytest.raises(PermissionError):
            npc.decide_game(replace(request(), actor_id='B'))
    finally:
        npc.store.close()


def test_context_budget_and_legacy_models_can_inject_optional_capability():
    npc = NPC('A', {}, _StubLLM())
    try:
        for i in range(25):
            npc.receive_game_event(replace(event(str(i)), content='公开发言' * 500))
        with pytest.raises(TypeError, match='未实现'):
            npc.decide_game(request())
        model = Model()
        npc.decide_game(request(), model=model)
        assert sum(len(m['content']) for m in model.context.memories) <= 6000
        assert len(model.context.memories) <= 16
        assert all(m['truncated'] for m in model.context.memories)
    finally:
        npc.store.close()
