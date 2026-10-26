"""第二个游戏独立运行，验证阶段、权限、结算和恢复，不评估模型博弈质量。"""
from dataclasses import replace
import json

import pytest

from game_agent import NPC
from game_agent.integration import ActionIntent, GameSession
from game_agent.memory import EventScope
from game_agent.scenarios.werewolf import WerewolfAdapter, WerewolfWorld
from tests.test_persistence import _StubLLM


ROLES = {'A': 'wolf', 'B': 'seer', 'C': 'villager', 'D': 'villager', 'E': 'villager', 'F': 'wolf'}


def choose(req, action=None, arguments=None):
    spec = next((s for s in req.actions if s.name == action), req.actions[0])
    if arguments is None:
        arguments = {p.name: (p.choices[0] if p.choices else '我仍在观察证据') for p in spec.parameters}
    return ActionIntent(req.instance_id, req.request_id, req.actor_id, req.state_version,
                        spec.name, arguments, '绝不能成为公开原文的私人策略')


class Model(_StubLLM):
    def __init__(self):
        self.contexts = []
    def decide_game(self, context):
        self.contexts.append(context)
        return choose(context.request)


def phase(adapter, overrides=None):
    for req in adapter.requests():
        adapter.submit(choose(req, **(overrides or {}).get(req.actor_id, {})))
    return adapter.resolve()


def test_private_views_and_native_legal_actions_have_no_space_dependency():
    world = WerewolfWorld('g', ROLES)
    adapter = WerewolfAdapter(world)
    assert not hasattr(world, 'locations') and not hasattr(world, 'health')
    assert {r.actor_id for r in adapter.requests()} == {'A', 'B', 'F'}
    assert '狼人队友：F' in world.view_for('A')
    assert '狼人队友' not in world.view_for('C')
    assert '真实身份：villager' in world.view_for('C')
    a = next(r for r in adapter.requests() if r.actor_id == 'A')
    assert 'F' not in a.actions[0].parameters[0].choices
    before = world.snapshot()
    with pytest.raises(ValueError):
        adapter.submit(choose(a, arguments={'target': 'F'}))
    assert world.snapshot() == before
    with pytest.raises(ValueError):
        world.request_for('C')


def test_simultaneous_night_resolves_after_all_and_dying_seer_still_receives_result():
    adapter = WerewolfAdapter(WerewolfWorld('g', ROLES))
    requests = adapter.requests()
    adapter.submit(choose(requests[0]))  # A 的首个合法目标 B
    with pytest.raises(ValueError, match='全部提交'):
        adapter.resolve()
    assert adapter.world.version == 0 and adapter.world.alive == set(ROLES)
    for r in adapter.requests():
        adapter.submit(choose(r))
    result = adapter.resolve()
    inspection = next(e for e in result if e.event_type == 'inspection_result')
    assert inspection.recipients == ('B',) and inspection.channel == 'private'
    assert '结果为狼人' in inspection.content
    assert 'B' not in adapter.world.alive
    assert adapter.world.actors_to_act() == ('A',)
    with pytest.raises(ValueError):
        adapter.submit(choose(requests[0]))


def test_sequential_speech_and_simultaneous_vote_tie():
    adapter = WerewolfAdapter(WerewolfWorld('g', ROLES))
    phase(adapter)
    while adapter.world.phase == 'speech':
        actor = adapter.requests()[0].actor_id
        phase(adapter, {actor: {'arguments': {'text': f'{actor} 的声明'}}})
        if adapter.world.phase == 'speech':
            assert f'{actor} 的声明' in adapter.requests()[0].view
    living = adapter.world.living()
    before = set(living)
    # 全部弃票按约定无人淘汰，且记录每人的选择。
    result = phase(adapter, {a: {'action': 'abstain', 'arguments': {}} for a in living})
    assert adapter.world.alive == before
    assert any('全部弃票' in e.content for e in result)
    assert adapter.world.phase == 'night' and adapter.world.round == 2


def test_same_generic_session_finishes_game_and_never_broadcasts_secrets():
    world, models, actors = WerewolfWorld('match', ROLES), {}, {}
    for name in ROLES:
        models[name] = Model()
        actors[name] = NPC(name, {'social': .4}, models[name])
    try:
        events = GameSession(WerewolfAdapter(world), actors).run(max_steps=100)
        assert world.winner in ('good', 'wolves', 'draw') and world.phase == 'finished'
        public = [e for e in events if e.channel == 'public']
        assert all('主持人反馈' not in e.content and '私人策略' not in e.content for e in public)
        assert any(e.event_type == 'public_speech' for e in public)
        assert actors['B'].store.count_events(EventScope(as_of=100, instance_id='match')) > 0
        for name in ('C', 'D', 'E'):
            for context in models[name].contexts:
                assert '狼人队友' not in context.request.view
                assert not any(m['event_type'] == 'inspection_result' for m in context.memories)
                role_memories = [m for m in context.memories if m['event_type'] == 'role_assignment']
                assert all('villager' in m['content'] for m in role_memories)
        assert len(models['B'].contexts) == 1  # 夜间淘汰后不再发言或投票
    finally:
        for npc in actors.values():
            npc.store.close()


def test_partial_batch_snapshot_and_pending_delivery_survive_json_restore():
    adapter = WerewolfAdapter(WerewolfWorld('g', ROLES))
    first = adapter.requests()[0]
    adapter.submit(choose(first))
    restored = WerewolfAdapter.restore(json.loads(json.dumps(adapter.snapshot())))
    assert {r.actor_id for r in restored.requests()} == {'B', 'F'}
    expected = phase(adapter)
    actual = phase(restored)
    assert actual == expected
    assert restored.world.snapshot() == adapter.world.snapshot()
    assert restored.pending_events() == adapter.pending_events()
    # 已结算请求不能在恢复后重放。
    with pytest.raises(ValueError):
        restored.submit(choose(first))


def test_real_npc_archive_partial_delivery_is_idempotent_after_restart(tmp_path, monkeypatch):
    world = WerewolfWorld('g', ROLES)
    adapter = WerewolfAdapter(world)
    actors = {a: NPC.create(a, {}, Model(), data_dir=str(tmp_path)) for a in ROLES}
    original = actors['B'].store.archive_input
    def fail(*a, **kw):
        raise OSError('archive offline')
    monkeypatch.setattr(actors['B'].store, 'archive_input', fail)
    with pytest.raises(OSError):
        GameSession(adapter, actors).deliver()
    assert actors['A'].store.archive_count() == 1
    state = json.loads(json.dumps(adapter.snapshot()))
    monkeypatch.setattr(actors['B'].store, 'archive_input', original)
    for npc in actors.values():
        npc.store.close()
    actors = {a: NPC.load(str(tmp_path / f'{a}.db'), Model()) for a in ROLES}
    try:
        restored = WerewolfAdapter.restore(state)
        GameSession(restored, actors).deliver()
        assert all(npc.store.archive_count() == 2 for npc in actors.values())
        assert not restored.pending_events()
    finally:
        for npc in actors.values():
            npc.store.close()


def test_good_victory_and_configured_round_limit_draw():
    roles = {'A': 'wolf', 'B': 'villager', 'C': 'villager', 'D': 'villager'}
    adapter = WerewolfAdapter(WerewolfWorld('g', roles))
    phase(adapter)  # B 被淘汰
    while adapter.world.phase == 'speech':
        phase(adapter)
    phase(adapter, {'A': {'action': 'abstain', 'arguments': {}},
                    'C': {'arguments': {'target': 'A'}}, 'D': {'arguments': {'target': 'A'}}})
    assert adapter.world.winner == 'good'
    adapter = WerewolfAdapter(WerewolfWorld('g2', roles, max_rounds=1))
    phase(adapter)
    while adapter.world.phase == 'speech':
        phase(adapter)
    phase(adapter, {a: {'action': 'abstain', 'arguments': {}} for a in adapter.world.living()})
    assert adapter.world.winner == 'draw'


def test_corrupted_request_snapshot_is_rejected():
    adapter = WerewolfAdapter(WerewolfWorld('g', ROLES))
    adapter.requests()
    state = adapter.snapshot()
    state['batch']['requests'][0]['view'] = '不属于真实个人视角'
    with pytest.raises(ValueError, match='不匹配'):
        WerewolfAdapter.restore(state)


@pytest.mark.parametrize('field,value', [('phase', 'unknown'), ('version', -1),
                                      ('winner', 'wolves'), ('alive', ['absent'])])
def test_corrupted_world_snapshot_is_rejected(field, value):
    state = WerewolfWorld('g', ROLES).snapshot()
    state[field] = value
    with pytest.raises(ValueError):
        WerewolfWorld.restore(state)


def test_json_key_sorting_does_not_change_seat_order_or_pending_requests():
    roles = {'Z': 'wolf', 'B': 'seer', 'Y': 'villager', 'A': 'villager'}
    adapter = WerewolfAdapter(WerewolfWorld('g', roles))
    expected = adapter.requests()
    state = json.loads(json.dumps(adapter.snapshot(), sort_keys=True))
    restored = WerewolfAdapter.restore(state)
    assert restored.world.actors == ('Z', 'B', 'Y', 'A')
    assert restored.requests() == expected


SKILL_ROLES = {'A': 'wolf', 'B': 'seer', 'C': 'witch', 'D': 'hunter',
               'E': 'villager', 'F': 'villager'}


def night(adapter, actions):
    for req in adapter.requests():
        action, arguments = actions[req.actor_id]
        adapter.submit(choose(req, action=action, arguments=arguments))
    return adapter.resolve()


def test_default_roles_are_ten_with_witch_and_hunter():
    from game_agent.scenarios.werewolf import DEFAULT_ROLES
    assert len(DEFAULT_ROLES) == 10
    assert sum(v == 'wolf' for v in DEFAULT_ROLES.values()) == 3
    assert set(DEFAULT_ROLES.values()) == {'wolf', 'seer', 'witch', 'hunter', 'villager'}
    assert list(DEFAULT_ROLES.values()).count('witch') == 1
    assert list(DEFAULT_ROLES.values()).count('hunter') == 1


def test_witch_saves_wolf_target_and_uses_antidote():
    adapter = WerewolfAdapter(WerewolfWorld('g', SKILL_ROLES))
    events = night(adapter, {
        'A': ('kill', {'target': 'E'}),
        'B': ('inspect', {'target': 'A'}),
        'C': ('save', {}),
    })
    assert 'E' in adapter.world.alive
    assert adapter.world.witch_antidote is False
    assert adapter.world.witch_poison is True
    assert adapter.world.phase == 'speech'
    assert any(e.event_type == 'witch_result' and e.recipients == ('C',)
               and '解药' in e.content for e in events)
    assert any(e.event_type == 'announcement' and '无人死亡' in e.content for e in events)


def test_witch_poison_kills_hunter_without_a_shot():
    adapter = WerewolfAdapter(WerewolfWorld('g', SKILL_ROLES))
    events = night(adapter, {
        'A': ('kill', {'target': 'D'}),
        'B': ('inspect', {'target': 'A'}),
        'C': ('poison', {'target': 'D'}),
    })
    assert 'D' not in adapter.world.alive
    assert adapter.world.witch_poison is False
    assert adapter.world.hunter_pending is None
    assert adapter.world.hunter_shot is False
    assert adapter.world.phase == 'speech'
    assert not any(e.event_type.startswith('hunter_') for e in events)


def test_hunter_shoots_after_wolf_kill_and_can_win():
    roles = {'A': 'wolf', 'B': 'seer', 'C': 'witch', 'D': 'hunter', 'E': 'villager'}
    adapter = WerewolfAdapter(WerewolfWorld('g', roles))
    night(adapter, {
        'A': ('kill', {'target': 'D'}),
        'B': ('inspect', {'target': 'A'}),
        'C': ('wait', {}),
    })
    assert adapter.world.phase == 'hunter'
    assert adapter.world.actors_to_act() == ('D',)
    request = adapter.requests()[0]
    assert {a.name for a in request.actions} == {'shoot', 'pass'}
    adapter.submit(choose(request, action='shoot', arguments={'target': 'A'}))
    events = adapter.resolve()
    assert adapter.world.winner == 'good'
    assert adapter.world.phase == 'finished'
    assert adapter.world.hunter_shot is True
    assert any(e.event_type == 'hunter_shot' and e.channel == 'public' for e in events)


def test_hunter_can_shoot_after_being_voted_out():
    adapter = WerewolfAdapter(WerewolfWorld('g', SKILL_ROLES))
    night(adapter, {
        'A': ('kill', {'target': 'E'}),
        'B': ('inspect', {'target': 'A'}),
        'C': ('wait', {}),
    })
    while adapter.world.phase == 'speech':
        phase(adapter)
    living = adapter.world.living()
    overrides = {a: ({'action': 'abstain', 'arguments': {}} if a == 'D'
                     else {'arguments': {'target': 'D'}}) for a in living}
    phase(adapter, overrides)
    assert adapter.world.phase == 'hunter'
    assert adapter.world.hunter_pending == 'D'
    request = adapter.requests()[0]
    adapter.submit(choose(request, action='shoot', arguments={'target': 'A'}))
    adapter.resolve()
    assert adapter.world.winner == 'good'
    assert adapter.world.phase == 'finished'
    assert adapter.world.hunter_shot is True
