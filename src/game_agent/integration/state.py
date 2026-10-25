"""适配器可组合使用的请求批与待投递队列，无游戏规则。"""
from dataclasses import asdict

from .contracts import ActionIntent, ActionSpec, DecisionRequest, GameEvent, ParameterSpec


def request_from_dict(row):
    return DecisionRequest(**dict(row, actions=tuple(ActionSpec(**dict(a,
        parameters=tuple(ParameterSpec(**p) for p in a['parameters']))) for a in row['actions'])))


class RequestBatch:
    def __init__(self):
        self.all: tuple[DecisionRequest, ...] = ()
        self.submitted: dict[str, ActionIntent] = {}

    def open(self, requests):
        if self.all:
            raise ValueError('上一批请求尚未结算')
        proposed = tuple(requests)
        if len({r.request_id for r in proposed}) != len(proposed):
            raise ValueError('请求 ID 重复')
        self.all = proposed

    def pending(self):
        return tuple(r for r in self.all if r.request_id not in self.submitted)

    def submit(self, intent):
        request = next((r for r in self.all if r.request_id == intent.request_id), None)
        if request is None:
            raise ValueError('请求不存在或已结算')
        request.validate(intent)
        original = self.submitted.get(intent.request_id)
        if original is not None and original != intent:
            raise ValueError('同一请求不能重复提交不同动作')
        self.submitted[intent.request_id] = ActionIntent(**asdict(intent))

    def intents(self):
        if not self.all or self.pending():
            raise ValueError('请求尚未全部提交')
        return tuple(self.submitted[r.request_id] for r in self.all)

    def clear(self):
        self.all, self.submitted = (), {}

    def snapshot(self):
        return {'requests': [asdict(r) for r in self.all],
                'submitted': [asdict(i) for i in self.submitted.values()]}

    @classmethod
    def restore(cls, state):
        batch = cls()
        batch.open(request_from_dict(r) for r in state['requests'])
        for row in state['submitted']:
            batch.submit(ActionIntent(**row))
        return batch


class EventOutbox:
    def __init__(self):
        self._events: dict[str, GameEvent] = {}

    def add(self, *events):
        proposed = dict(self._events)
        for event in events:
            if event.event_id in proposed and proposed[event.event_id] != event:
                raise ValueError('相同事件 ID 内容冲突')
            proposed[event.event_id] = event
        self._events = proposed

    def pending(self):
        return tuple(self._events.values())

    def ack(self, event_id):
        self._events.pop(event_id, None)

    def snapshot(self):
        return [asdict(e) for e in self.pending()]

    @classmethod
    def restore(cls, rows):
        outbox = cls()
        outbox.add(*(GameEvent(**row) for row in rows))
        return outbox
