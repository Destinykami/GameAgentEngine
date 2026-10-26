"""两个独立游戏使用同一 NPC 协议；默认离线，不在导入时创建世界。"""
from __future__ import annotations

import json
from pathlib import Path
import uuid

from ..integration import ActionIntent, GameSession


class DemoModel:
    """只验证接入，不代表有效的博弈策略。"""
    def decide_game(self, context):
        request = context.request
        spec = next((a for a in request.actions if a.name == 'talk'), request.actions[0])
        arguments = {p.name: p.choices[0] if p.choices else '我会继续观察公开信息。'
                     for p in spec.parameters}
        return ActionIntent(request.instance_id, request.request_id, request.actor_id,
                            request.state_version, spec.name, arguments)

    def score_importance(self, *args):
        return 5

    def complete(self, context):
        return '我听到了。'

    def perceive_action(self, npc, actor, action, context=''):
        return f'{actor} 对 {npc} 做了以下动作：{action}'

    def generate_plan(self, *args, **kwargs):
        return []

    def decompose_activity(self, *args):
        return []

    def judge_trust(self, *args):
        return 0.0


def run_demo(game: str, data_dir: str, *, model=None):
    from ..cognition.npc import NPC
    from ..adapters import SpatialAdapter
    from ..scenarios.werewolf import DEFAULT_ROLES, WerewolfAdapter, WerewolfWorld
    from ..world.runtime import World
    from ..world.entities import Location

    if game not in ('spatial', 'werewolf'):
        raise ValueError('未知示例游戏')
    directory = Path(data_dir)
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    if any(directory.iterdir()):
        raise ValueError('示例目录必须为空，已有数据不会被覆盖')
    directory.chmod(0o700)
    model = model if model is not None else DemoModel()
    instance_id = f'{game}-{uuid.uuid4().hex}'
    actors, spatial = {}, None
    try:
        if game == 'werewolf':
            roles = dict(DEFAULT_ROLES)
            for name in roles:
                actors[name] = NPC.create(name, {'social': .5}, model, data_dir=str(directory))
            adapter = WerewolfAdapter(WerewolfWorld(instance_id, roles))
            events = GameSession(adapter, actors).run(max_steps=200)
            winner = adapter.world.winner
        else:
            spatial = World('空间接入示例', [Location('广场'), Location('工坊', 1, 0)],
                            path=str(directory / 'world.db'))
            for name in ('A', 'B'):
                actors[name] = spatial.add_npc(name, {'social': .5}, model,
                                               data_dir=str(directory), location='广场')
            adapter = SpatialAdapter(spatial, instance_id)
            session, events = GameSession(adapter, actors), []
            for now in (1.0, 2.0):
                adapter.begin_turn(now)
                events.extend(session.run())
            winner = None
            spatial.save_checkpoint(str(directory / 'spatial-checkpoints'))
        for actor in actors.values():
            actor.save()
        # 主持人快照包括私密身份和个人视角，与公共产物明确分开。
        private_path = directory / 'adapter-state.private.json'
        private_path.write_text(json.dumps(adapter.snapshot(), ensure_ascii=False, indent=2), encoding='utf-8')
        private_path.chmod(0o600)
        summary = {'game': game, 'instance_id': instance_id, 'finished': adapter.finished,
                   'winner': winner, 'public_events': [e.content for e in events if e.channel == 'public']}
        (directory / 'public-result.json').write_text(
            json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
        return summary
    finally:
        if spatial is not None:
            spatial.close()
        else:
            for actor in actors.values():
                actor.store.close()
