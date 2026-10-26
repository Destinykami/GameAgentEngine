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

RULES = ('简化狼人杀：夜间狼人先密谈、再投票选出袭击目标；随后预言家查验、女巫用药。'
         '白天按座次发言，然后同时投票或弃票。'
         '女巫有解药和毒药各一次，同夜只能用一种；女巫会看到狼人投票选定的目标，再决定是否用解药。'
         '猎人被狼人或投票淘汰时可开枪带走一名存活者，被毒杀不能开枪。'
         '投票平票无人淘汰，狼人目标平票按座次。淘汰不公布身份，无遗言。'
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
        self.round, self.version = 1, 0
        self.winner = None
        self.speakers: list[str] = []
        self.speaker_index = 0
        self.transcript: list[str] = []
        self.wolf_speakers: list[str] = []
        self.wolf_speaker_index = 0
        self.wolf_chat: list[str] = []
        self.wolf_target: str | None = None
        self.witch_seen_target: str | None = None
        self.witch_antidote = 'witch' in roles.values()
        self.witch_poison = 'witch' in roles.values()
        self.hunter_shot = 'hunter' not in roles.values()
        self.hunter_pending: str | None = None
        self.hunter_next_phase: str | None = None
        self.phase = 'wolf_talk'
        self._start_night()

    def living(self):
        return tuple(a for a in self.actors if a in self.alive)

    def _living_wolves(self):
        return tuple(a for a in self.living() if self._roles[a] == 'wolf')

    def actors_to_act(self):
        if self.winner:
            return ()
        if self.phase == 'wolf_talk':
            return (self.wolf_speakers[self.wolf_speaker_index],) \
                if self.wolf_speaker_index < len(self.wolf_speakers) else ()
        if self.phase == 'wolf_vote':
            return self._living_wolves()
        if self.phase == 'seer':
            return tuple(a for a in self.living() if self._roles[a] == 'seer')
        if self.phase == 'witch':
            return tuple(a for a in self.living() if self._roles[a] == 'witch')
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
        if self.phase == 'wolf_talk':
            return (ActionSpec('say', '向狼人队友发送一条夜间交流',
                               (ParameterSpec('text', max_length=1000),)),)
        targets = tuple(a for a in self.living() if a != actor)
        if self.phase == 'wolf_vote':
            wolf_targets = tuple(a for a in targets if self._roles[a] != 'wolf')
            return (ActionSpec('kill', '狼人投票选择本夜袭击目标',
                               (ParameterSpec('target', choices=wolf_targets),)),)
        if self.phase == 'seer':
            return (ActionSpec('inspect', '查验一名存活玩家的阵营',
                               (ParameterSpec('target', choices=targets),)),)
        if self.phase == 'witch':
            actions = []
            if self.witch_antidote:
                actions.append(ActionSpec('save', '使用解药救下今晚被狼人选中的目标'))
            if self.witch_poison:
                actions.append(ActionSpec('poison', '使用毒药毒杀一名存活玩家',
                                          (ParameterSpec('target', choices=targets),)))
            actions.append(ActionSpec('wait', '本夜不使用药水'))
            return tuple(actions)
        if self.phase == 'hunter':
            actions = []
            if targets:
                actions.append(ActionSpec('shoot', '开枪带走一名存活玩家',
                                          (ParameterSpec('target', choices=targets),)))
            actions.append(ActionSpec('pass', '放弃本次开枪'))
            return tuple(actions)
        if self.phase == 'speech':
            return (ActionSpec('speak', '公开发表一段声明，其他人不会自动逐句回复',
                               (ParameterSpec('text', max_length=2000),)),)
        if self.phase == 'vote':
            return (ActionSpec('vote', '投票淘汰一名存活角色',
                               (ParameterSpec('target', choices=targets),)),
                    ActionSpec('abstain', '本次弃票'))
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
            if self.wolf_chat:
                view += '\n狼人夜间交流：\n' + '\n'.join(self.wolf_chat)
        elif role == 'witch':
            view += ('女巫药水：解药' + ('可用' if self.witch_antidote else '已用完')
                     + '，毒药' + ('可用' if self.witch_poison else '已用完') + '。')
            if self.phase in ('seer', 'witch') and self.wolf_target is not None:
                view += f'今晚狼人投票选定的目标：{self.wolf_target}。'
            elif self.witch_seen_target is not None:
                view += f'你昨夜看到狼人目标：{self.witch_seen_target}。'
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
                private += '夜间先与队友交流，再投票选择目标。'
            elif role == 'seer':
                private += '每晚可查验一名存活玩家的阵营。'
            elif role == 'witch':
                private += '你有解药和毒药各一次，同夜只能用一种；你会看到狼人投票选定的目标，再决定是否用解药。'
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

    def _start_night(self):
        self.phase = 'wolf_talk'
        self.wolf_speakers = list(self._living_wolves())
        self.wolf_speaker_index = 0
        self.wolf_chat = []
        self.wolf_target = None
        self.witch_seen_target = None

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

    def _wolf_vote(self, intents, events):
        kills = [i.arguments['target'] for i in intents if i.action == 'kill']
        target = None
        if kills:
            votes = Counter(kills)
            target = next(a for a in self.actors if votes[a] == max(votes.values()))
        self.wolf_target = target
        self.witch_seen_target = target
        wolves = self._living_wolves()
        witch = next((a for a in self.living() if self._roles[a] == 'witch'), None)
        if target is not None:
            self._emit(events, 'wolf_result', f'狼人投票选定目标：{target}。',
                       wolves, 'team', participants=(target,))
            if witch is not None:
                self._emit(events, 'wolf_target',
                           f'主持人反馈：今晚狼人投票选定的目标是 {target}。',
                           (witch,), 'private', participants=(target,))
        if any(self._roles[a] == 'seer' for a in self.living()):
            self.phase = 'seer'
        elif any(self._roles[a] == 'witch' for a in self.living()):
            self.phase = 'witch'
        else:
            self._resolve_night(events)

    def _seer(self, intents, events):
        intent = intents[0]
        target = intent.arguments['target']
        result = '狼人' if self._roles[target] == 'wolf' else '好人'
        self._emit(events, 'inspection_result',
                   f'主持人反馈：你查验 {target}，结果为{result}。',
                   (intent.actor_id,), 'private',
                   participants=(intent.actor_id, target))
        if any(self._roles[a] == 'witch' for a in self.living()):
            self.phase = 'witch'
        else:
            self._resolve_night(events)

    def _witch(self, intents, events):
        intent = intents[0]
        witch = intent.actor_id
        action, target = intent.action, intent.arguments.get('target')
        if action == 'save':
            self.witch_antidote = False
            content = (f'你使用解药救下了 {self.wolf_target}。'
                       if self.wolf_target else '你使用解药，但今晚无人被狼人选为目标。')
            self._emit(events, 'witch_result', content, (witch,), 'private')
        elif action == 'poison':
            self.witch_poison = False
            self._emit(events, 'witch_result', f'你使用毒药毒杀了 {target}。',
                       (witch,), 'private', participants=(witch, target))
        else:
            self._emit(events, 'witch_result', '你本夜没有使用药水。',
                       (witch,), 'private')
        self._resolve_night(events, witch_action=action, witch_target=target)

    def _resolve_night(self, events, *, witch_action=None, witch_target=None):
        victim = self.wolf_target
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
        self.wolf_target, self.wolf_chat = None, []
        self.wolf_speakers, self.wolf_speaker_index = [], 0
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
            self.round += 1
            self._start_night()
        self._finish_turn(events)

    def advance(self, intents):
        expected = self.actors_to_act()
        if len(intents) != len(expected) or {i.actor_id for i in intents} != set(expected):
            raise ValueError('尚未收齐本阶段行动')
        for intent in intents:
            self.request_for(intent.actor_id).validate(intent)  # 真实状态再次校验
        self.version += 1
        events = []

        if self.phase == 'wolf_talk':
            intent = intents[0]
            line = f'{intent.actor_id} 说：{intent.arguments["text"]}'
            self.wolf_chat.append(line)
            self._emit(events, 'wolf_chat', line, self._living_wolves(), 'team',
                       actor=intent.actor_id, evidence='utterance')
            self.wolf_speaker_index += 1
            if self.wolf_speaker_index == len(self.wolf_speakers):
                self.phase = 'wolf_vote'
        elif self.phase == 'wolf_vote':
            self._wolf_vote(intents, events)
        elif self.phase == 'seer':
            self._seer(intents, events)
        elif self.phase == 'witch':
            self._witch(intents, events)
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
            self.round += 1
            self._start_night()
            self._finish_turn(events)
        return tuple(events)

    def snapshot(self):
        """主持人私密快照，不能作为玩家视图或公开回放。"""
        return json_copy({'schema_version': 1, 'instance_id': self.instance_id,
            'roles': self._roles, 'actors': self.actors, 'max_rounds': self.max_rounds,
            'alive': self.living(), 'round': self.round, 'version': self.version,
            'phase': self.phase, 'winner': self.winner, 'speakers': self.speakers,
            'speaker_index': self.speaker_index, 'transcript': self.transcript,
            'wolf_speakers': self.wolf_speakers, 'wolf_speaker_index': self.wolf_speaker_index,
            'wolf_chat': self.wolf_chat, 'wolf_target': self.wolf_target,
            'witch_seen_target': self.witch_seen_target,
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
                    'transcript', 'wolf_speakers', 'wolf_speaker_index', 'wolf_chat',
                    'wolf_target', 'witch_seen_target'):
            setattr(world, key, json_copy(state.get(key, getattr(world, key))))
        for key in ('witch_antidote', 'witch_poison', 'hunter_shot',
                    'hunter_pending', 'hunter_next_phase'):
            setattr(world, key, json_copy(state.get(key, getattr(world, key))))
        if (type(world.round) is not int or world.round < 1 or type(world.version) is not int
                or world.version < 0 or world.phase not in
                ('wolf_talk', 'wolf_vote', 'seer', 'witch', 'hunter',
                 'speech', 'vote', 'finished')
                or not world.alive or not isinstance(world.transcript, list)
                or any(not isinstance(t, str) for t in world.transcript)):
            raise ValueError('非法对局阶段或时间状态')
        if (not isinstance(world.wolf_chat, list)
                or any(not isinstance(t, str) for t in world.wolf_chat)
                or not isinstance(world.wolf_speakers, list)
                or any(a not in world.actors or world._roles[a] != 'wolf'
                       for a in world.wolf_speakers)
                or type(world.wolf_speaker_index) is not int
                or world.wolf_speaker_index < 0
                or world.wolf_target is not None and
                (world.wolf_target not in world.actors or
                 world._roles[world.wolf_target] == 'wolf' or
                 world.wolf_target not in world.alive)
                or world.witch_seen_target is not None and
                world.witch_seen_target not in world.actors):
            raise ValueError('非法狼人夜间状态')
        if any(type(getattr(world, key)) is not bool for key in
               ('witch_antidote', 'witch_poison', 'hunter_shot')):
            raise ValueError('非法药水或猎人状态')
        if world.phase == 'wolf_talk':
            expected_wolves = [a for a in world.living() if world._roles[a] == 'wolf']
            if (world.wolf_speakers != expected_wolves
                    or world.wolf_speaker_index >= len(world.wolf_speakers)
                    or world.wolf_target is not None):
                raise ValueError('狼人交流阶段状态不一致')
        if world.phase in ('seer', 'witch') and world.wolf_target is None:
            raise ValueError('夜间技能阶段缺少狼人目标')
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
