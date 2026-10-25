"""不继承 World 的第三方游戏通过相同接口协调 NPC。"""
from dataclasses import replace

import pytest

from game_agent.integration import (ActionIntent, ActionSpec, DecisionRequest,
                                    GameEvent, GameSession, ParameterSpec)
from game_agent.integration.state import EventOutbox, RequestBatch


def request(actor='A'):
    return DecisionRequest('game', f'r-{actor}', actor, 'v1', 'trade', 1,
        '进行交易', '你有五枚金币', (ActionSpec('purchase', '购买物品', (
            ParameterSpec('item', choices=('矿石', '药水')),
            ParameterSpec('quantity', 'integer', minimum=1, maximum=5))),))


def intent(req, **arguments):
    return ActionIntent(req.instance_id, req.request_id, req.actor_id,
                        req.state_version, 'purchase', arguments)


@pytest.mark.parametrize('arguments', [
    {'item': '矿石', 'quantity': 0}, {'item': '矿石', 'quantity': True},
    {'item': '剑', 'quantity': 1}, {'item': '矿石'},
    {'item': '矿石', 'quantity': 1, 'secret': 'extra'},
])
def test_dynamic_action_validation(arguments):
    with pytest.raises(ValueError):
        request().validate(intent(request(), **arguments))


def test_binding_stale_unknown_and_duplicate_submission():
    req = request()
    good = intent(req, item='矿石', quantity=1)
    batch = RequestBatch()
    batch.open((req,))
    for bad in (replace(good, actor_id='B'), replace(good, instance_id='other'),
                replace(good, state_version='v2'), replace(good, action='attack')):
        with pytest.raises(ValueError):
            batch.submit(bad)
    assert batch.pending() == (req,)
    batch.submit(good)
    batch.submit(good)
    with pytest.raises(ValueError):
        batch.submit(replace(good, arguments={'item': '药水', 'quantity': 1}))
    restored = RequestBatch.restore(batch.snapshot())
    assert restored.intents() == (good,)
    batch.clear()
    with pytest.raises(ValueError):
        batch.submit(good)


class ExternalGame:
    def __init__(self):
        self.finished = False
        self.batch, self.outbox = RequestBatch(), EventOutbox()
        self.batch.open((request('A'), request('B')))
        self.outbox.add(GameEvent('game', 'opening', 0, 'notice', '公共公告', ('A', 'B')))
        self.resolutions = 0

    def requests(self):
        return self.batch.pending()

    def submit(self, action):
        self.batch.submit(action)

    def resolve(self):
        self.batch.intents()
        self.batch.clear()
        self.resolutions += 1
        self.finished = True
        event = GameEvent('game', 'result', 2, 'result', '个人结果', ('A',), channel='private')
        self.outbox.add(event)
        return (event,)

    def pending_events(self):
        return self.outbox.pending()

    def ack_event(self, event_id):
        self.outbox.ack(event_id)


class Actor:
    def __init__(self, name):
        self.name, self.received = name, {}
        self.fail_delivery = self.fail_decision = False
        self.calls = 0

    def receive_game_event(self, event):
        if self.fail_delivery:
            raise OSError('archive unavailable')
        self.received[event.event_id] = event

    def decide_game(self, req):
        self.calls += 1
        if self.fail_decision:
            raise RuntimeError('model unavailable')
        return intent(req, item='矿石', quantity=1)


def test_partial_delivery_retries_before_any_decision_and_private_audience():
    game, a, b = ExternalGame(), Actor('A'), Actor('B')
    session = GameSession(game, {'A': a, 'B': b})
    b.fail_delivery = True
    with pytest.raises(OSError):
        session.step()
    assert a.calls == b.calls == 0 and len(game.pending_events()) == 1
    b.fail_delivery = False
    session.run()
    assert set(a.received) == {'opening', 'result'}
    assert set(b.received) == {'opening'}
    assert game.resolutions == 1 and not game.pending_events()


def test_failed_decision_retains_submitted_batch_and_resumes_only_missing():
    game, a, b = ExternalGame(), Actor('A'), Actor('B')
    session = GameSession(game, {'A': a, 'B': b})
    b.fail_decision = True
    with pytest.raises(RuntimeError):
        session.step()
    assert game.resolutions == 0 and game.requests() == (request('B'),)
    b.fail_decision = False
    session.step()
    assert a.calls == 1 and b.calls == 2 and game.resolutions == 1


def test_missing_binding_never_acknowledges_or_partially_delivers():
    game, a = ExternalGame(), Actor('A')
    with pytest.raises(ValueError, match='未绑定'):
        GameSession(game, {'A': a}).deliver()
    assert not a.received and len(game.pending_events()) == 1


def test_world_objects_boolean_times_and_half_batches_are_rejected():
    with pytest.raises(ValueError, match='World'):
        replace(request(), view=object())
    with pytest.raises(ValueError, match='有限数值'):
        replace(request(), now=True)
    batch = RequestBatch()
    with pytest.raises(ValueError):
        batch.open((request(), request()))
    assert not batch.all
    outbox = EventOutbox()
    e = GameEvent('g', 'e', 1, 'notice', '原公告', ('A',))
    with pytest.raises(ValueError):
        outbox.add(e, replace(e, content='冲突公告'))
    assert not outbox.pending()
