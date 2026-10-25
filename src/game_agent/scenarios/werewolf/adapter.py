"""将独立狼人杀运行时接入通用 NPC 协议。"""
from ...integration.state import EventOutbox, RequestBatch
from .world import WerewolfWorld


class WerewolfAdapter:
    def __init__(self, world: WerewolfWorld):
        self.world = world
        self._batch, self._outbox = RequestBatch(), EventOutbox()
        self._outbox.add(*world.opening_events())

    @property
    def finished(self):
        return self.world.winner is not None

    def requests(self):
        if self.finished:
            return ()
        if not self._batch.all:
            self._batch.open(self.world.request_for(a) for a in self.world.actors_to_act())
        return self._batch.pending()

    def submit(self, intent):
        if self.finished:
            raise ValueError('对局已经结束')
        self.world.request_for(intent.actor_id).validate(intent)
        self._batch.submit(intent)

    def resolve(self):
        events = self.world.advance(self._batch.intents())
        self._batch.clear()
        self._outbox.add(*events)
        return events

    def pending_events(self):
        return self._outbox.pending()

    def ack_event(self, event_id):
        self._outbox.ack(event_id)

    def snapshot(self):
        return {'schema_version': 1, 'world': self.world.snapshot(),
                'batch': self._batch.snapshot(), 'outbox': self._outbox.snapshot()}

    @classmethod
    def restore(cls, state):
        if state['schema_version'] != 1:
            raise ValueError('不支持的适配器快照版本')
        adapter = cls(WerewolfWorld.restore(state['world']))
        adapter._batch = RequestBatch.restore(state['batch'])
        for r in adapter._batch.all:
            expected = adapter.world.request_for(r.actor_id)
            if r != expected:
                raise ValueError('请求快照与当前对局不匹配')
        adapter._outbox = EventOutbox.restore(state['outbox'])
        if any(e.instance_id != adapter.world.instance_id or
               not set(e.recipients) <= set(adapter.world.actors) or e.now > adapter.world.version
               for e in adapter._outbox.pending()):
            raise ValueError('待投递事件与对局不匹配')
        return adapter
