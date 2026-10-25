"""现有空间 World 的显式接入路径，不替换旧自治循环。"""
from __future__ import annotations

import hashlib
import json

from ..integration import ActionSpec, DecisionRequest, GameEvent, ParameterSpec
from ..integration.state import EventOutbox, RequestBatch
from ..world.entities import distance, location_distance
from ..world.events import VisualEvent


class SpatialAdapter:
    def __init__(self, world, instance_id: str, actor_ids=None):
        if not instance_id:
            raise ValueError('空间实例 ID 不能为空')
        self.world, self.instance_id = world, instance_id
        self.actor_ids = tuple(actor_ids if actor_ids is not None else world.npc_names())
        if not self.actor_ids or len(set(self.actor_ids)) != len(self.actor_ids):
            raise ValueError('空间角色集合为空或重复')
        if any(world.get(a) is None for a in self.actor_ids):
            raise ValueError('空间角色不存在')
        self._batch, self._outbox = RequestBatch(), EventOutbox()
        self._active, self._turn = False, 0
        self._fingerprint = ''

    @property
    def finished(self):
        return not self._active

    def _world_version(self):
        state = [(e.name, e.location.name, e.location.x, e.location.y, e.health,
                  e.attack, e.defense, e.dead) for e in self.world.entities.values()]
        return hashlib.sha256(json.dumps([self.world.name, self.world.clock,
            self.world.perception_radius, [(p.name, p.x, p.y) for p in self.world.locations.values()],
            state], ensure_ascii=False).encode()).hexdigest()

    def _actions(self, actor):
        actions = [ActionSpec('wait', '等待观察')]
        actions.append(ActionSpec('move', '移动到一个区域', (
            ParameterSpec('dest', choices=tuple(self.world.locations)),)))
        targets = tuple(e.name for e in self.world.entities.values() if e is not actor and
                        e.is_alive() and distance(actor, e) <= self.world.perception_radius)
        if targets:
            target = ParameterSpec('target', choices=targets)
            actions.extend((ActionSpec('talk', '向目标说话', (target, ParameterSpec('utterance'))),
                            ActionSpec('attack', '攻击目标', (target,)),
                            ActionSpec('help', '帮助目标', (target,)),
                            ActionSpec('hide', '帮助目标藏匿', (target,)),
                            ActionSpec('flee', '逃离附近威胁')))
        return tuple(actions)

    def begin_turn(self, now):
        if self._active or self._outbox.pending():
            raise ValueError('上一回合尚未完成或事件未投递')
        if now < self.world.clock:
            raise ValueError('空间时间不能倒退')
        self.world.step(now)
        self._turn += 1
        self._fingerprint = self._world_version()
        requests = []
        for actor_id in self.actor_ids:
            actor = self.world.get(actor_id)
            if not actor.is_alive():
                continue
            view = self.world.agent_perception(actor) + '\n自身状态: ' + self.world.agent_state(actor)
            view += '\n自己的近期经历: ' + ' | '.join(actor.history[-10:])
            npc = self.world.npc(actor_id)
            if npc is not None:
                visible = {e.name for e in self.world.entities.values() if e is not actor and
                           e.is_alive() and distance(actor, e) <= self.world.perception_radius}
                view += '\n自己的关系背景: ' + npc.decision_context(visible)
                view += '\n对可见对象的信任: ' + ', '.join(
                    f'{name}:{npc.trust_toward(name):+.2f}' for name in sorted(visible)
                    if npc.has_relationship(name))
            requests.append(DecisionRequest(self.instance_id,
                f'{self.instance_id}:{self._turn}:{actor_id}', actor_id, self._fingerprint,
                'spatial_turn', self.world.clock, actor.goal, view, self._actions(actor),
                '选择一个当前合法动作；只根据自己的可见信息和经历行动。'))
        self._batch.open(requests)
        self._active = bool(requests)

    def requests(self):
        return self._batch.pending()

    def submit(self, intent):
        if not self._active or self._world_version() != self._fingerprint:
            raise ValueError('空间状态已变化，请求过期')
        self._batch.submit(intent)

    def resolve(self):
        intents = self._batch.intents()
        if self._world_version() != self._fingerprint:
            raise ValueError('空间状态已变化，请求过期')
        self.world.visual_events = []
        error = None
        for intent in intents:
            actor = self.world.get(intent.actor_id)
            if not actor.is_alive():
                continue
            try:
                spec = next((a for a in self._actions(actor) if a.name == intent.action), None)
                if spec is None:
                    raise ValueError('动作已不再合法')
                spec.validate(intent.arguments)
            except ValueError:
                self.world.visual_events.append(VisualEvent(
                    'conversation' if intent.action == 'talk' else intent.action,
                    actor.name, self.world.clock, target=intent.arguments.get('target', ''),
                    location=actor.location.name, success=False, failure_reason='状态变化后动作不再合法'))
                continue
            try:
                self.world.execute_action(actor, {'action': intent.action, **intent.arguments})
                visual = self.world.visual_events[-1]
                if visual.success and intent.action in self.world.INTERRUPT_ACTIONS:
                    npc = self.world.npc(actor.name)
                    if npc is not None:
                        try:
                            npc.replan(self.world.clock, visual.describe())
                        except Exception:
                            pass  # 与既有自治循环相同：重规划失败不撤销已提交动作
                if visual.success and intent.action == 'attack':
                    target_id = intent.arguments['target']
                    target_npc = self.world.npc(target_id)
                    if target_npc is not None and self.world.get(target_id).is_alive():
                        try:
                            target_npc.replan(self.world.clock, f'被 {actor.name} 攻击了', actor.name)
                        except Exception:
                            pass
            except Exception as exc:
                error = error or exc
                self.world.visual_events.append(VisualEvent('action_error', actor.name,
                    self.world.clock, target=intent.arguments.get('target', ''),
                    success=False, failure_reason='动作执行异常'))
        self._batch.clear()
        self._active = False
        # 实际结算只投递给直接相关方；世界公告按已声明的位置/范围投递。
        events = []
        for index, visual in enumerate(self.world.visual_events):
            if visual.type == 'world_event':
                recipients = tuple(a for a in self.actor_ids if self.world.get(a).is_alive() and
                    (not visual.location or location_distance(
                        self.world.locations[visual.location], self.world.get(a))
                     <= self.world.perception_radius))
            else:
                recipients = tuple(a for a in self.actor_ids if a in (visual.actor, visual.target))
            if not recipients:
                continue
            content = visual.describe() if visual.type != 'action_error' else f'{visual.actor} 的动作执行异常'
            events.append(GameEvent(self.instance_id, f'{self._turn}:{index}', self.world.clock,
                'spatial_result' if visual.success else 'spatial_failure', content, recipients,
                'public' if visual.type == 'world_event' else 'direct', visual.actor,
                tuple(p for p in (visual.actor, visual.target) if p)))
        self._outbox.add(*events)
        self.world.flush_social(self.world.clock)
        self.world.step(self.world.clock)
        if error is not None:
            raise error  # 待投递事件保留，已执行动作不会重放
        return tuple(events)

    def pending_events(self):
        return self._outbox.pending()

    def ack_event(self, event_id):
        self._outbox.ack(event_id)

    def snapshot(self):
        return {'version': 1, 'instance_id': self.instance_id, 'actor_ids': list(self.actor_ids),
                'world_version': self._world_version(), 'turn': self._turn, 'active': self._active,
                'request_version': self._fingerprint, 'batch': self._batch.snapshot(),
                'outbox': self._outbox.snapshot()}

    @classmethod
    def restore(cls, world, state):
        if state['version'] != 1:
            raise ValueError('不支持的空间适配器快照版本')
        adapter = cls(world, state['instance_id'], state['actor_ids'])
        if adapter._world_version() != state['world_version']:
            raise ValueError('适配器快照与空间世界状态不匹配')
        adapter._turn, adapter._active = state['turn'], state['active']
        adapter._fingerprint = state['request_version']
        adapter._batch = RequestBatch.restore(state['batch'])
        if any(r.instance_id != adapter.instance_id or r.actor_id not in adapter.actor_ids
               or r.state_version != adapter._fingerprint for r in adapter._batch.all):
            raise ValueError('请求快照与空间适配器不匹配')
        adapter._outbox = EventOutbox.restore(state['outbox'])
        return adapter
