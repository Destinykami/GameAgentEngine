"""权威身份、阶段、动作与结算。此模块不依赖 NPC、模型、坐标或血量。"""
from __future__ import annotations

from collections import Counter

from ...integration import ActionSpec, DecisionRequest, GameEvent, ParameterSpec
from ...integration.contracts import json_copy


DEFAULT_ROLES = {
    '1号': 'wolf', '2号': 'wolf', '3号': 'wolf',
    '4号': 'seer', '5号': 'witch', '6号': 'hunter',
    '7号': 'villager', '8号': 'villager', '9号': 'villager', '10号': 'villager',
}
ROLE_TYPES = {'wolf', 'seer', 'witch', 'hunter', 'villager'}
UNIQUE_ROLES = {'seer', 'witch', 'hunter'}

RULES = ('简化狼人杀：夜间狼人袭击、预言家查验、女巫用药；白天按座次发言，然后同时投票或弃票。'
         '女巫有解药和毒药各一次，同夜只能用一种；解药救下今晚狼人选择的目标，毒药毒杀一人。'
         '猎人被狼人或投票淘汰时可开枪带走一名存活者，被毒杀不能开枪。'
         '投票平票无人淘汰，夜间目标平票按座次。淘汰不公布身份，无遗言。'
         '狼人清零好人胜，狼人达到好人人数狼人胜。允许策略性谎报身份和查验，'
         '公开声明不等于主持人反馈；自己的真实身份和技能反馈不可在私人记忆中改写。')


class WerewolfWorld:
    def __init__(self, instance_id: str, roles: dict[str, str], *, max_rounds: int = 16):
        if not isinstance(instance_id, str) or not instance_id or not isinstance(roles, dict) or not 3 <= len(roles) <= 64:
            raise ValueError('需要实例 ID 和 3 到 64 个角色')
        if any(not isinstance(a, str) or not a or len(a) > 128 for a in roles):
            raise ValueError('角色 ID 无效')
        if set(roles.values()) - ROLE_TYPES:
            raise ValueError('不支持的身份')
        wolves = sum(r == 'wolf' for r in roles.values())
        duplicates = [r for r in UNIQUE_ROLES if list(roles.values()).count(r) > 1]
        if not wolves or wolves * 2 >= len(roles) or duplicates:
            raise ValueError('初始好人须多于狼人，至少一狼、预言家/女巫/猎人各最多一名')
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
        # 女巫每种药水各一次；猎人开枪也各一局一次。没有对应身份时视为已用完。
        self.witch_antidote = 'witch' in roles.values()
        self.witch_poison = 'witch' in roles.values()
        self.hunter_shot = 'hunter' not in roles.values()
        self.hunter_pending: str | None = None
        self.hunter_next_phase: str | None = None

    def living(self):
        return tuple(a for a in self.actors if a in self.alive)

    def actors_to_act(self):
        if self.winner:
            return ()
        if self.phase == 'night':
            return tuple(a for a in self.living()
                         if self._roles[a] in ('wolf', 'seer', 'witch'))
        if self.phase == 'hunter':
            return (self.hunter_pending,) if self.hunter_pending else ()
        if self.phase == 'speech':
            return (self.speakers[self.speaker_index],)
        if self.phase == 'vote':
            return self.living()
        return ()

    def actions_for(self, actor):
        if actor not in self.actors_to_act():
            return ()
        if self.phase == 'speech':
            return (ActionSpec('speak', '公开发表一段声明，其他人不会自动逐句回复',
                               (ParameterSpec('text', max_length=2000),)),)
        if self.phase == 'hunter':
            targets = tuple(a for a in self.living() if a != actor)
            actions = []
            if targets:
                actions.append(ActionSpec('shoot', '开枪带走一名存活玩家',
                                          (ParameterSpec('target', choices=targets),)))
            actions.append(ActionSpec('pass', '放弃本次开枪'))
            return tuple(actions)
        targets = tuple(a for a in self.living() if a != actor)
        if self.phase == 'vote':
            return (ActionSpec('vote', '投票淘汰一名存活角色',
                               (ParameterSpec('target', choices=targets),)),
                    ActionSpec('abstain', '本次弃票'))
        role = self._roles[actor]
        if role == 'wolf':
            wolf_targets = tuple(a for a in targets if self._roles[a] != 'wolf')
            return (ActionSpec('kill', '与狼人队友共同选择本夜目标',
                               (ParameterSpec('target', choices=wolf_targets),)),)
        if role == 'seer':
            return (ActionSpec('inspect', '查验一名存活玩家的阵营',
                               (ParameterSpec('target', choices=targets),)),)
        if role == 'witch':
            actions = []
            if self.witch_antidote:
                actions.append(ActionSpec('save', '使用解药救下今晚被狼人袭击的人'))
            if self.witch_poison:
                actions.append(ActionSpec('poison', '使用毒药毒杀一名存活玩家',
                                          (ParameterSpec('target', choices=targets),)))
            actions.append(ActionSpec('wait', '本夜不使用药水'))
            return tuple(actions)
        return ()

    def view_for(self, actor):
        if actor not in self._roles:
            raise ValueError('未知角色')
        view = f'第 {self.round} 轮，阶段 {self.phase}；存活：' + '、'.join(self.living())
        view += f'。你的真实身份：{self._roles[actor]}。'
        role = self._roles[actor]
        if role == 'wolf':
            view += '狼人队友：' + '、'.join(
                a for a in self.actors if a != actor and self._roles[a] == 'wolf')
        elif role == 'witch':
            view += ('女巫药水：解药' + ('可用' if self.witch_antidote else '已用完')
                     + '，毒药' + ('可用' if self.witch_poison else '已用完') + '。'
                     + '你与狼人同时行动，解药会救下今晚狼人选择的目标。')
        elif role == 'hunter':
            view += ('猎人技能：你被狼人或投票淘汰时可开枪；被毒杀时不能开枪。'
                     + ('本局已使用。' if self.hunter_shot else '本局尚未使用。'))
        if self.phase == 'hunter':
            view += '你已出局，可选择开枪目标或放弃。'
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
            role = self._roles[actor]
            private = f'你的真实身份：{role}。'
            if role == 'wolf':
                private += '狼人队友：' + '、'.join(
                    a for a in self.actors if a != actor and self._roles[a] == 'wolf')
            elif role == 'seer':
                private += '每晚可查验一名存活玩家的阵营。'
            elif role == 'witch':
                private += '你有解药和毒药各一次，同夜只能用一种；解药救下狼人目标，毒药毒杀一人。'
            elif role == 'hunter':
                private += '你被狼人或投票淘汰时可开枪带走一名存活者，被毒杀不能开枪。'
            else:
                private += '你没有夜间技能。'
            events.append(GameEvent(self.instance_id, f'role:{actor}', 0, 'role_assignment',
                private, (actor,), 'private'))
        return tuple(events)

    def _emit(self, events, event_type, content, recipients=None, channel='public',
              actor=None, participants=(), evidence='observation'):
        event = GameEvent(self.instance_id, f'{self.version}:{len(events)}', float(self.version),
            event_type, content, self.actors if recipients is None else recipients,
            channel, actor, participants, evidence)
        events.append(event)
        if channel == 'public':
            self.transcript.append(content)
        return event

    def _start_speech(self):
        self.speakers, self.speaker_index = list(self.living()), 0
        self.phase = 'speech'

    def _hunter_name(self):
        return next((a for a, role in self._roles.items() if role == 'hunter'), None)

    def _begin_hunter(self, name, next_phase):
        self.hunter_pending, self.hunter_next_phase = name, next_phase
        self.phase = 'hunter'

    def _finish_turn(self, events):
        self._check_winner()
        if self.winner is None and self.round > self.max_rounds:
            self.winner = 'draw'
        if self.winner:
            self.phase = 'finished'
            self._emit(events, 'game_over', f'对局结束：{self.winner}。')

    def _check_winner(self):
        wolves = sum(self._roles[a] == 'wolf' for a in self.alive)
        good = len(self.alive) - wolves
        if not wolves:
            self.winner = 'good'
        elif wolves >= good:
            self.winner = 'wolves'

    def _night(self, intents, events):
        kills = []
        witch_action, witch_target = None, None
        for intent in intents:
            if intent.action == 'inspect':
                target = intent.arguments['target']
                result = '狼人' if self._roles[target] == 'wolf' else '好人'
                self._emit(events, 'inspection_result',
                           f'主持人反馈：你查验 {target}，结果为{result}。',
                           (intent.actor_id,), 'private',
                           participants=(intent.actor_id, target))
            elif intent.action == 'kill':
                kills.append(intent.arguments['target'])
            elif intent.action == 'save':
                witch_action = 'save'
            elif intent.action == 'poison':
                witch_action, witch_target = 'poison', intent.arguments['target']
            elif intent.action == 'wait':
                witch_action = 'wait'
        victim = None
        if kills:
            votes = Counter(kills)
            victim = next(a for a in self.actors if votes[a] == max(votes.values()))
        wolves = tuple(a for a in self.living() if self._roles[a] == 'wolf')
        if victim is not None:
            self._emit(events, 'wolf_result', f'本夜狼人选定目标：{victim}。',
                       wolves, 'team', participants=(victim,))
        witch = next((a for a in self.living() if self._roles[a] == 'witch'), None)
        if witch_action == 'save':
            self.witch_antidote = False
            content = (f'你使用解药救下了 {victim}。' if victim
                       else '你使用解药，但本夜无人被狼人袭击。')
            self._emit(events, 'witch_result', content, (witch,), 'private')
        elif witch_action == 'poison':
            self.witch_poison = False
            self._emit(events, 'witch_result', f'你使用毒药毒杀了 {witch_target}。',
                       (witch,), 'private', participants=(witch, witch_target))
        elif witch_action == 'wait':
            self._emit(events, 'witch_result', '你本夜没有使用药水。', (witch,), 'private')

        saved = victim is not None and witch_action == 'save'
        deaths = {}
        if victim is not None and not saved:
            deaths[victim] = 'wolf'
        if witch_action == 'poison':
            deaths[witch_target] = 'poison'
        for name in deaths:
            self.alive.discard(name)
            self._emit(events, 'elimination', f'第 {self.round} 夜，{name} 被淘汰。',
                       participants=(name,))
        if not deaths:
            self._emit(events, 'announcement', f'第 {self.round} 夜，无人死亡。')

        hunter = self._hunter_name()
        if (hunter is not None and hunter in deaths and not self.hunter_shot
                and deaths[hunter] != 'poison'):
            self._begin_hunter(hunter, 'speech')
            return
        self._start_speech()
        self._finish_turn(events)

    def _hunter(self, intents, events):
        intent = intents[0]
        if intent.action == 'shoot':
            target = intent.arguments['target']
            self.alive.discard(target)
            self._emit(events, 'hunter_shot',
                       f'{intent.actor_id} 开枪带走了 {target}。',
                       actor=intent.actor_id,
                       participants=(intent.actor_id, target))
        else:
            self._emit(events, 'hunter_pass', f'{intent.actor_id} 放弃了开枪。',
                       actor=intent.actor_id, participants=(intent.actor_id,))
        self.hunter_shot = True
        next_phase = self.hunter_next_phase
        self.hunter_pending, self.hunter_next_phase = None, None
        if next_phase == 'speech':
            self._start_speech()
        else:
            self.phase, self.round = 'night', self.round + 1
        self._finish_turn(events)

    def advance(self, intents):
        expected = self.actors_to_act()
        if len(intents) != len(expected) or {i.actor_id for i in intents} != set(expected):
            raise ValueError('尚未收齐本阶段行动')
        for intent in intents:
            self.request_for(intent.actor_id).validate(intent)  # 真实状态再次校验
        self.version += 1
        events = []

        if self.phase == 'night':
            self._night(intents, events)
        elif self.phase == 'hunter':
            self._hunter(intents, events)
        elif self.phase == 'speech':
            intent = intents[0]
            self._emit(events, 'public_speech', f'{intent.actor_id} 说：{intent.arguments["text"]}',
                       actor=intent.actor_id, participants=(intent.actor_id,),
                       evidence='utterance')
            self.speaker_index += 1
            if self.speaker_index == len(self.speakers):
                self.phase = 'vote'
        elif self.phase == 'vote':
            votes = Counter(i.arguments['target'] for i in intents if i.action == 'vote')
            record = '；'.join(f'{i.actor_id}→{i.arguments.get("target", "弃票")}' for i in intents)
            self._emit(events, 'vote_result', f'第 {self.round} 轮票型：{record}')
            top = [a for a in self.living() if votes and votes[a] == max(votes.values())]
            if len(top) == 1:
                victim = top[0]
                self.alive.discard(victim)
                self._emit(events, 'elimination', f'{victim} 被投票淘汰。',
                           participants=(victim,))
                if victim == self._hunter_name() and not self.hunter_shot:
                    self._begin_hunter(victim, 'night')
                    return tuple(events)
            else:
                self._emit(events, 'announcement', '投票平票或全部弃票，无人淘汰。')
            self.phase, self.round = 'night', self.round + 1
            self._finish_turn(events)
        return tuple(events)

    def snapshot(self):
        """主持人私密快照，不能作为玩家视图或公开回放。"""
        return json_copy({'schema_version': 1, 'instance_id': self.instance_id,
            'roles': self._roles, 'actors': self.actors, 'max_rounds': self.max_rounds,
            'alive': self.living(), 'round': self.round, 'version': self.version,
            'phase': self.phase, 'winner': self.winner, 'speakers': self.speakers,
            'speaker_index': self.speaker_index, 'transcript': self.transcript,
            'witch_antidote': self.witch_antidote, 'witch_poison': self.witch_poison,
            'hunter_shot': self.hunter_shot, 'hunter_pending': self.hunter_pending,
            'hunter_next_phase': self.hunter_next_phase})

    @classmethod
    def restore(cls, state):
        if state['schema_version'] != 1:
            raise ValueError('不支持的对局快照版本')
        seats = state.get('actors', list(state['roles']))
        if len(seats) != len(set(seats)) or set(seats) != set(state['roles']):
            raise ValueError('快照席位与角色不一致')
        world = cls(state['instance_id'], {a: state['roles'][a] for a in seats},
                    max_rounds=state['max_rounds'])
        world.alive = set(state['alive'])
        if not world.alive <= set(world.actors):
            raise ValueError('快照包含未知存活角色')
        for key in ('round', 'version', 'phase', 'winner', 'speakers', 'speaker_index',
                    'transcript'):
            setattr(world, key, json_copy(state[key]))
        for key in ('witch_antidote', 'witch_poison', 'hunter_shot',
                    'hunter_pending', 'hunter_next_phase'):
            setattr(world, key, json_copy(state.get(key, getattr(world, key))))
        if (type(world.round) is not int or world.round < 1 or type(world.version) is not int
                or world.version < 0 or world.phase not in
                ('night', 'speech', 'vote', 'hunter', 'finished')
                or not world.alive or not isinstance(world.transcript, list)
                or any(not isinstance(t, str) for t in world.transcript)):
            raise ValueError('非法对局阶段或时间状态')
        if any(type(getattr(world, key)) is not bool for key in
               ('witch_antidote', 'witch_poison', 'hunter_shot')):
            raise ValueError('非法药水或猎人状态')
        if world.hunter_pending is not None:
            if (world.phase != 'hunter' or world.hunter_pending not in world.actors
                    or world._roles[world.hunter_pending] != 'hunter'
                    or world.hunter_pending in world.alive
                    or world.hunter_shot
                    or world.hunter_next_phase not in ('speech', 'night')):
                raise ValueError('非法猎人待处理状态')
        elif world.hunter_next_phase is not None:
            raise ValueError('没有待处理猎人却记录了下一阶段')
        if world.phase == 'hunter' and world.hunter_pending is None:
            raise ValueError('猎人阶段缺少待处理猎人')
        expected = None
        wolves = sum(world._roles[a] == 'wolf' for a in world.alive)
        if not wolves:
            expected = 'good'
        elif wolves >= len(world.alive) - wolves:
            expected = 'wolves'
        elif world.round > world.max_rounds:
            expected = 'draw'
        if world.phase == 'hunter':
            if world.winner is not None:
                raise ValueError('猎人阶段不能已有胜负')
        elif world.winner != expected or (world.phase == 'finished') != (world.winner is not None):
            raise ValueError('快照胜负与存活状态不一致')
        if (not isinstance(world.speakers, list) or not set(world.speakers) <= set(world.actors)
                or type(world.speaker_index) is not int or world.speaker_index < 0):
            raise ValueError('非法发言顺序')
        if world.phase == 'speech' and (world.speakers != list(world.living())
                or world.speaker_index >= len(world.speakers)):
            raise ValueError('发言阶段与存活角色不一致')
        return world
