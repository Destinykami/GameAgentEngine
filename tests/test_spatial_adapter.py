"""空间适配器复用原 World，不要求旧自治入口改用新模型。"""
import json

import pytest

from game_agent import Location, World
from game_agent.adapters import SpatialAdapter
from game_agent.integration import ActionIntent, GameSession
from game_agent.memory import EventScope
from tests.test_persistence import _StubLLM


class Model(_StubLLM):
    def __init__(self, action='talk', arguments=None):
        self.action = action
        self.arguments = arguments if arguments is not None else {'target': 'B', 'utterance': '你好'}
    def decide_game(self, ctx):
        r = ctx.request
        return ActionIntent(r.instance_id, r.request_id, r.actor_id, r.state_version,
                            self.action, self.arguments)


def setup(tmp_path):
    w = World('W', [Location('L', 0, 0), Location('far', 10, 10)])
    a = w.add_npc('A', {}, Model(), data_dir=str(tmp_path), location='L')
    b = w.add_npc('B', {}, Model('wait', {}), data_dir=str(tmp_path), location='L')
    b.llm.arguments = {}
    return w, a, b


def test_same_session_drives_real_world_talk_and_preserves_originals(tmp_path):
    w, a, b = setup(tmp_path)
    try:
        adapter = SpatialAdapter(w, 'spatial-1')
        adapter.begin_turn(1)
        requests = adapter.requests()
        assert len(requests) == 2
        assert 'talk' in {s.name for s in requests[0].actions}
        session = GameSession(adapter, {'A': a, 'B': b})
        events = session.run()
        assert adapter.finished and any('你好' in e.content for e in events)
        assert a.store.count_events(EventScope(as_of=1, instance_id='spatial-1')) > 0
        assert b.store.search_archive('你好', player_id='A')
        adapter.begin_turn(2)
        session.run()
        assert adapter.finished
    finally:
        w.close()


def test_far_targets_and_external_changes_are_rejected_before_execution(tmp_path):
    w, a, b = setup(tmp_path)
    try:
        w.get('B').move(w.locations['far'])
        adapter = SpatialAdapter(w, 'g', ('A',))
        adapter.begin_turn(1)
        r = adapter.requests()[0]
        assert 'talk' not in {s.name for s in r.actions}
        with pytest.raises(ValueError):
            adapter.submit(ActionIntent('g', r.request_id, 'A', r.state_version, 'talk',
                                         {'target': 'B', 'utterance': '远程讲话'}))
        good = ActionIntent('g', r.request_id, 'A', r.state_version, 'wait')
        w.get('B').move(w.locations['L'])
        with pytest.raises(ValueError, match='过期'):
            adapter.submit(good)
    finally:
        w.close()


def test_simultaneous_snapshot_rechecks_targets_after_earlier_actor_moves(tmp_path):
    w, a, b = setup(tmp_path)
    try:
        adapter = SpatialAdapter(w, 'g')
        adapter.begin_turn(1)
        first, second = adapter.requests()
        adapter.submit(ActionIntent('g', first.request_id, 'A', first.state_version,
                                    'move', {'dest': 'far'}))
        adapter.submit(ActionIntent('g', second.request_id, 'B', second.state_version,
                                    'attack', {'target': 'A'}))
        events = adapter.resolve()
        assert w.get('A').health == 100
        assert any('不再合法' in e.content for e in events)
    finally:
        w.close()


def test_pending_requests_and_outbox_snapshot_are_bound_to_world(tmp_path):
    w, a, b = setup(tmp_path)
    try:
        adapter = SpatialAdapter(w, 'g')
        adapter.begin_turn(1)
        r = adapter.requests()[0]
        adapter.submit(ActionIntent('g', r.request_id, 'A', r.state_version, 'wait'))
        state = json.loads(json.dumps(adapter.snapshot()))
        restored = SpatialAdapter.restore(w, state)
        assert len(restored.requests()) == 1
        GameSession(restored, {'A': a, 'B': b}).step()
        w.get('A').take_damage(1)
        with pytest.raises(ValueError, match='不匹配'):
            SpatialAdapter.restore(w, state)
    finally:
        w.close()


def test_adapter_continues_after_real_world_checkpoint_restore(tmp_path):
    w = World('W', [Location('L', 0, 0)], path=str(tmp_path / 'live/world.db'))
    try:
        for name in ('A', 'B'):
            w.add_npc(name, {}, Model('wait', {}), data_dir=str(tmp_path / 'live'))
        adapter = SpatialAdapter(w, 'g')
        adapter.begin_turn(1)
        first = adapter.requests()[0]
        adapter.submit(ActionIntent('g', first.request_id, 'A', first.state_version, 'wait'))
        state = adapter.snapshot()
        w.save_checkpoint(str(tmp_path / 'checkpoints'))
    finally:
        w.close()
    restored = World.from_checkpoint(str(tmp_path / 'checkpoints'), str(tmp_path / 'resumed'), Model('wait', {}))
    try:
        adapter = SpatialAdapter.restore(restored, state)
        assert len(adapter.requests()) == 1
        GameSession(adapter, {n: restored.npc(n) for n in restored.npc_names()}).step()
        assert adapter.finished
    finally:
        restored.close()
