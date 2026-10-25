"""权威身份、阶段、动作与结算。此模块不依赖 NPC、模型、坐标或血量。"""
from __future__ import annotations

from collections import Counter

from ...integration import ActionSpec, DecisionRequest, GameEvent, ParameterSpec
from ...integration.contracts import json_copy


RULES = ('简化狼人杀：夜间狼人选目标、预言家查验；白天按座次发言，然后同时投票或弃票。'
         '投票平票无人淘汰，夜间目标平票按座次。淘汰不公布身份，无遗言。'
         '狼人清零好人胜，狼人达到好人人数狼人胜。允许策略性谎报身份和查验，'
         '公开声明不等于主持人反馈；自己的真实身份和技能反馈不可在私人记忆中改写。')


class WerewolfWorld:
    def __init__(self, instance_id: str, roles: dict[str, str], *, max_rounds: int = 16):
        if not isinstance(instance_id, str) or not instance_id or not isinstance(roles, dict) or not 3 <= len(roles) <= 64:
            raise ValueError('需要实例 ID 和 3 到 64 个角色')
        if any(not isinstance(a, str) or not a or len(a) > 128 for a in roles):
            raise ValueError('角色 ID 无效')
        if set(roles.values()) - {'wolf', 'seer', 'villager'}:
            raise ValueError('不支持的身份')
        wolves = sum(r == 'wolf' for r in roles.values())
        if not wolves or wolves * 2 >= len(roles) or list(roles.values()).count('seer') > 1:
            raise ValueError('初始好人须多于狼人，至少一狼、最多一名预言家')
        if isinstance(max_rounds, bool) or not isinstance(max_rounds, int) or max_rounds < 1:
            raise ValueError('轮数上限须为正整数')
        self.instance_id, self._roles = instance_id, dict(roles)
        self.actors = tuple(roles)
        self.alive = set(roles)
        self.max_rounds = max_rounds
        self.round, self.version, self.phase = 1, 0, 'night'
        self.winner = None
        self.speakers: list[str] = []
        self.speaker_index = 0
        self.transcript: list[str] = []

    def living(self):
        return tuple(a for a in self.actors if a in self.alive)

    def actors_to_act(self):
        if self.winner:
            return ()
        if self.phase == 'night':
            return tuple(a for a in self.living() if self._roles[a] in ('wolf', 'seer'))
        if self.phase == 'speech':
            return (self.speakers[self.speaker_index],)
        return self.living()

    def actions_for(self, actor):
        if actor not in self.actors_to_act():
            return ()
        if self.phase == 'speech':
            return (ActionSpec('speak', '公开发表一段声明，其他人不会自动逐句回复',
                               (ParameterSpec('text', max_length=2000),)),)
        targets = tuple(a for a in self.living() if a != actor and
                        (self.phase != 'night' or self._roles[actor] != 'wolf' or self._roles[a] != 'wolf'))
        target = ParameterSpec('target', choices=targets)
        if self.phase == 'vote':
            return (ActionSpec('vote', '投票淘汰一名存活角色', (target,)),
                    ActionSpec('abstain', '本次弃票'))
        return (ActionSpec('kill' if self._roles[actor] == 'wolf' else 'inspect',
                           '提交本夜行动，所有夜间行动提交后统一结算', (target,)),)

    def view_for(self, actor):
        if actor not in self._roles:
            raise ValueError('未知角色')
        view = f'第 {self.round} 轮，阶段 {self.phase}；存活：' + '、'.join(self.living())
        view += f'。你的真实身份：{self._roles[actor]}。'
        if self._roles[actor] == 'wolf':
            view += '狼人队友：' + '、'.join(a for a in self.actors if a != actor and self._roles[a] == 'wolf')
        view += '\n最近公开记录：\n' + '\n'.join(self.transcript[-20:])
        return view

    def request_for(self, actor):
        if actor not in self.actors_to_act():
            raise ValueError('该角色当前无行动权限')
        return DecisionRequest(self.instance_id, f'{self.instance_id}:{self.version}:{actor}',
            actor, str(self.version), self.phase, float(self.version),
            '让狼人阵营获胜' if self._roles[actor] == 'wolf' else '找出并淘汰所有狼人',
            self.view_for(actor), self.actions_for(actor), RULES)

    def opening_events(self):
        events = [GameEvent(self.instance_id, 'opening', 0, 'announcement',
            '对局开始。席位：' + '、'.join(self.actors), self.actors)]
        for actor in self.actors:
            private = f'你的真实身份：{self._roles[actor]}。'
            if self._roles[actor] == 'wolf':
                private += '狼人队友：' + '、'.join(a for a in self.actors if a != actor and self._roles[a] == 'wolf')
            events.append(GameEvent(self.instance_id, f'role:{actor}', 0, 'role_assignment',
                private, (actor,), 'private'))
        return tuple(events)

    def _check_winner(self):
        wolves = sum(self._roles[a] == 'wolf' for a in self.alive)
        good = len(self.alive) - wolves
        if not wolves:
            self.winner = 'good'
        elif wolves >= good:
            self.winner = 'wolves'

    def advance(self, intents):
        expected = self.actors_to_act()
        if len(intents) != len(expected) or {i.actor_id for i in intents} != set(expected):
            raise ValueError('尚未收齐本阶段行动')
        for intent in intents:
            self.request_for(intent.actor_id).validate(intent)  # 真实状态再次校验
        self.version += 1
        events = []
        def emit(event_type, content, recipients=None, channel='public', actor=None,
                 participants=(), evidence='observation'):
            e = GameEvent(self.instance_id, f'{self.version}:{len(events)}', float(self.version),
                event_type, content, self.actors if recipients is None else recipients,
                channel, actor, participants, evidence)
            events.append(e)
            if channel == 'public':
                self.transcript.append(content)

        if self.phase == 'night':
            kills = []
            for intent in intents:
                target = intent.arguments['target']
                if intent.action == 'inspect':
                    result = '狼人' if self._roles[target] == 'wolf' else '好人'
                    emit('inspection_result', f'主持人反馈：你查验 {target}，结果为{result}。',
                         (intent.actor_id,), 'private', participants=(intent.actor_id, target))
                else:
                    kills.append(target)
            votes = Counter(kills)
            victim = next(a for a in self.actors if votes[a] == max(votes.values()))
            wolves = tuple(a for a in self.living() if self._roles[a] == 'wolf')
            emit('wolf_result', f'本夜狼人选定目标：{victim}。', wolves, 'team', participants=(victim,))
            self.alive.remove(victim)
            emit('elimination', f'第 {self.round} 夜，{victim} 被淘汰。', participants=(victim,))
            self.speakers, self.speaker_index = list(self.living()), 0
            self.phase = 'speech'
        elif self.phase == 'speech':
            intent = intents[0]
            emit('public_speech', f'{intent.actor_id} 说：{intent.arguments["text"]}',
                 actor=intent.actor_id, participants=(intent.actor_id,), evidence='utterance')
            self.speaker_index += 1
            if self.speaker_index == len(self.speakers):
                self.phase = 'vote'
        else:
            votes = Counter(i.arguments['target'] for i in intents if i.action == 'vote')
            record = '；'.join(f'{i.actor_id}→{i.arguments.get("target", "弃票")}' for i in intents)
            emit('vote_result', f'第 {self.round} 轮票型：{record}')
            top = [a for a in self.living() if votes and votes[a] == max(votes.values())]
            if len(top) == 1:
                victim = top[0]
                self.alive.remove(victim)
                emit('elimination', f'{victim} 被投票淘汰。', participants=(victim,))
            else:
                emit('announcement', '投票平票或全部弃票，无人淘汰。')
            self.phase = 'night'
            self.round += 1
        self._check_winner()
        if self.winner is None and self.round > self.max_rounds:
            self.winner = 'draw'
        if self.winner:
            self.phase = 'finished'
            emit('game_over', f'对局结束：{self.winner}。')
        return tuple(events)

    def snapshot(self):
        """主持人私密快照，不能作为玩家视图或公开回放。"""
        return json_copy({'schema_version': 1, 'instance_id': self.instance_id,
            'roles': self._roles, 'max_rounds': self.max_rounds, 'alive': self.living(),
            'round': self.round, 'version': self.version, 'phase': self.phase,
            'winner': self.winner, 'speakers': self.speakers,
            'speaker_index': self.speaker_index, 'transcript': self.transcript})

    @classmethod
    def restore(cls, state):
        if state['schema_version'] != 1:
            raise ValueError('不支持的对局快照版本')
        world = cls(state['instance_id'], state['roles'], max_rounds=state['max_rounds'])
        world.alive = set(state['alive'])
        if not world.alive <= set(world.actors):
            raise ValueError('快照包含未知存活角色')
        for key in ('round', 'version', 'phase', 'winner', 'speakers', 'speaker_index', 'transcript'):
            setattr(world, key, json_copy(state[key]))
        if (type(world.round) is not int or world.round < 1 or type(world.version) is not int
                or world.version < 0 or world.phase not in ('night', 'speech', 'vote', 'finished')
                or not world.alive or not isinstance(world.transcript, list)
                or any(not isinstance(t, str) for t in world.transcript)):
            raise ValueError('非法对局阶段或时间状态')
        expected = None
        wolves = sum(world._roles[a] == 'wolf' for a in world.alive)
        if not wolves:
            expected = 'good'
        elif wolves >= len(world.alive) - wolves:
            expected = 'wolves'
        elif world.round > world.max_rounds:
            expected = 'draw'
        if world.winner != expected or (world.phase == 'finished') != (world.winner is not None):
            raise ValueError('快照胜负与存活状态不一致')
        if (not isinstance(world.speakers, list) or not set(world.speakers) <= set(world.actors)
                or type(world.speaker_index) is not int or world.speaker_index < 0):
            raise ValueError('非法发言顺序')
        if world.phase == 'speech' and (world.speakers != list(world.living())
                or world.speaker_index >= len(world.speakers)):
            raise ValueError('发言阶段与存活角色不一致')
        return world
