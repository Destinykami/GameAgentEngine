"""狼人杀公共回放运行器；只整理 GameEvent 与快照，不改游戏规则。"""
from __future__ import annotations

import json
import os
import secrets
import uuid

from ..cognition.npc import NPC
from ..integration import GameSession
from ..scenarios.werewolf import (
    DEFAULT_ROLES, WerewolfAdapter, WerewolfWorld, random_personas)
from .artifacts import TimelineWriter, reset_directory
from .game_demo import DemoModel


PRIVATE_EVENT_TYPES = {'role_assignment', 'inspection_result', 'wolf_result',
                       'wolf_chat', 'witch_result'}


def _parse_votes(content: str) -> dict:
    """从世界固定的票型文本解析 {投票者: 目标或 None}；不解析模型原始输出。"""
    if '：' not in content:
        return {}
    votes = {}
    for part in content.split('：', 1)[1].split('；'):
        if '→' not in part:
            continue
        actor, target = part.split('→', 1)
        target = target.strip()
        votes[actor.strip()] = None if target in ('弃票', '') else target
    return votes


def _event_payload(event, *, god: bool) -> dict:
    payload = {'id': event.event_id, 'type': event.event_type,
               'channel': event.channel, 'content': event.content}
    if event.actor_id:
        payload['actor'] = event.actor_id
    if event.event_type == 'public_speech' and '说：' in event.content:
        payload['text'] = event.content.split('说：', 1)[1]
    if event.event_type == 'vote_result':
        payload['votes'] = _parse_votes(event.content)
    if event.event_type == 'elimination':
        payload['target'] = event.participants[0] if event.participants else None
    if event.event_type == 'game_over' and '：' in event.content:
        payload['winner'] = event.content.rsplit('：', 1)[1].rstrip('。')
    if god:
        payload['recipients'] = list(event.recipients)
        payload['participants'] = list(event.participants)
        payload['evidence_kind'] = event.evidence_kind
    return payload


def _step_payload(index: int, world: WerewolfWorld, events, *, god: bool) -> dict:
    snapshot = world.snapshot()
    public_events = [e for e in events if god or e.channel == 'public']
    votes = {}
    for event in public_events:
        if event.event_type == 'vote_result':
            votes = _parse_votes(event.content)
    return {
        'step': index,
        'round': snapshot['round'],
        'phase': snapshot['phase'],
        'version': snapshot['version'],
        'alive': list(snapshot['alive']),
        'events': [_event_payload(e, god=god) for e in public_events],
        'votes': votes,
        'winner': snapshot['winner'],
    }


def _write_json(path: str, value) -> None:
    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
    with open(path, 'w', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)


def run_werewolf_replay(data_dir: str, public_dir: str, *, model=None,
                        publish_god: bool = False, roles=None,
                        persona_seed: int | None = None,
                        max_rounds: int = 16, max_steps: int = 1000) -> dict:
    """跑完一局并输出公共时间线/直播；可选把上帝文件发布到前端目录。"""
    if persona_seed is not None and (isinstance(persona_seed, bool)
                                      or not isinstance(persona_seed, int)):
        raise ValueError('人格随机种子须为整数')
    reset_directory(data_dir)
    os.makedirs(public_dir, exist_ok=True)
    roles = dict(roles or DEFAULT_ROLES)
    seed = persona_seed if persona_seed is not None else secrets.randbits(31)
    personas = random_personas(roles, seed)
    instance_id = 'werewolf-' + uuid.uuid4().hex
    world = WerewolfWorld(instance_id, roles, max_rounds=max_rounds)
    adapter = WerewolfAdapter(world)
    model = model if model is not None else DemoModel()
    actors = {}
    writer = None
    public_steps, god_steps = [], []
    try:
        for name in roles:
            actors[name] = NPC.create(name, dict(personas[name]), model, data_dir=data_dir)
        session = GameSession(adapter, actors)
        metadata = {'schema_version': 1, 'game': 'werewolf',
                    'instance_id': instance_id, 'seats': list(roles),
                    'max_rounds': max_rounds, 'persona_seed': seed}
        writer = TimelineWriter(os.path.join(public_dir, 'werewolf_live.jsonl'), metadata)

        # 开场事件在首次 step() 投递前捕获，否则 public 公告会丢失。
        opening = adapter.pending_events()
        opening_public = _step_payload(0, world, opening, god=False)
        opening_god = _step_payload(0, world, opening, god=True)
        public_steps.append(opening_public)
        god_steps.append(opening_god)
        writer.append(opening_public)

        while not adapter.finished and len(public_steps) <= max_steps:
            events = session.step()
            if not events and adapter.finished:
                break
            index = len(public_steps)
            public_step = _step_payload(index, world, events, god=False)
            god_step = _step_payload(index, world, events, god=True)
            public_steps.append(public_step)
            god_steps.append(god_step)
            writer.append(public_step)

        if not adapter.finished:
            raise RuntimeError('达到回放步数上限，对局尚未结束')
        god = {**metadata, 'roles': dict(roles), 'personas': personas, 'steps': god_steps}
        _write_json(os.path.join(data_dir, 'werewolf_god.json'), god)
        if publish_god:
            _write_json(os.path.join(public_dir, 'werewolf_god.json'), god)
        _write_json(os.path.join(data_dir, 'adapter-state.private.json'), adapter.snapshot())
        writer.finish({'winner': world.winner, 'finished': True})
        writer.write_final(os.path.join(public_dir, 'werewolf_timeline.json'), metadata)
        return {'game': 'werewolf', 'instance_id': instance_id,
                'winner': world.winner, 'steps': len(public_steps),
                'persona_seed': seed,
                'public_timeline': os.path.join(public_dir, 'werewolf_timeline.json'),
                'public_live': os.path.join(public_dir, 'werewolf_live.jsonl'),
                'god': os.path.join(data_dir, 'werewolf_god.json')}
    finally:
        if writer is not None:
            writer.close()
        for actor in actors.values():
            actor.store.close()
