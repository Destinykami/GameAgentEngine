"""只协调请求与可靠投递；不访问任何游戏的权威状态。"""
from __future__ import annotations

from typing import Mapping, Protocol

from .contracts import ActionIntent, DecisionRequest, GameAdapter, GameEvent


class GameActor(Protocol):
    name: str
    def decide_game(self, request: DecisionRequest) -> ActionIntent: ...
    def receive_game_event(self, event: GameEvent) -> str: ...


class GameSession:
    def __init__(self, adapter: GameAdapter, actors: Mapping[str, GameActor]):
        self.adapter = adapter
        self.actors = dict(actors)
        if any(actor.name != key for key, actor in self.actors.items()):
            raise ValueError('角色绑定 ID 必须与 NPC 名称一致')

    def deliver(self) -> None:
        for event in self.adapter.pending_events():
            for recipient in event.recipients:
                if recipient not in self.actors:
                    raise ValueError(f'事件接收者未绑定: {recipient}')
            for recipient in event.recipients:
                self.actors[recipient].receive_game_event(event)
            self.adapter.ack_event(event.event_id)

    def step(self) -> tuple[GameEvent, ...]:
        """返回主持人级结果；公开展示须仅选择 public 频道。"""
        self.deliver()
        if self.adapter.finished:
            return ()
        for request in self.adapter.requests():
            if request.actor_id not in self.actors:
                raise ValueError(f'决策角色未绑定: {request.actor_id}')
            intent = self.actors[request.actor_id].decide_game(request)
            request.validate(intent)
            self.adapter.submit(intent)
        events = self.adapter.resolve()
        self.deliver()
        return events

    def run(self, max_steps: int = 1000) -> tuple[GameEvent, ...]:
        events = []
        for _ in range(max_steps):
            events.extend(self.step())
            if self.adapter.finished:
                return tuple(events)
        raise RuntimeError('达到运行步数上限，游戏状态保留，尚未结束')
