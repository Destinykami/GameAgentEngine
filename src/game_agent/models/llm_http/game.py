"""动态动作决策；规则与动作说明仅来自已筛选请求，语义校验失败重试一次。"""
from dataclasses import asdict
import json

from ...integration.contracts import ActionIntent


_OUTPUT_KEYS = {'action', 'arguments', 'private_note'}
_SYSTEM = '你是游戏 NPC 决策器。只使用提供的个人视角和记忆，遵守当前游戏规则。'


def _persona_guidance(traits) -> str:
    """把随机人格数值转成可执行的表达倾向，避免所有村民同一口吻。"""
    try:
        social = float(traits.get('social', 0.5))
    except (TypeError, ValueError):
        social = 0.5
    try:
        goal = float(traits.get('goal_oriented', 0.5))
    except (TypeError, ValueError):
        goal = 0.5
    parts = []
    if social >= 0.65:
        parts.append('你偏外向，愿意主动点名、质疑或提出结盟。')
    elif social <= 0.35:
        parts.append('你偏内敛，发言简短谨慎，不轻易站队。')
    else:
        parts.append('你社交风格平衡，既不闷着也不强行带节奏。')
    if goal >= 0.65:
        parts.append('你目标导向强，优先谈票型、证据和下一步行动。')
    elif goal <= 0.35:
        parts.append('你更关注关系和情绪，不急着推票。')
    else:
        parts.append('你在目标与关系之间取平衡。')
    return ' '.join(parts)


def _phase_guidance(phase: str) -> str:
    if phase == 'speech':
        return ('这是公开发言。用第一人称和符合你人格的语气；提出至少一个前面玩家没有明确提出的'
                '观察、怀疑或计划；不要复述或照抄最近发言，不要使用相同句式。')
    if phase == 'wolf_talk':
        return ('这是狼人密谈。给出具体目标、理由或试探方案，不要复述公开发言；'
                '可以提出与队友不同的方案。')
    if phase in ('vote', 'wolf_vote'):
        return '根据你自己的视角和目标做决定，不要因为别人已经表态就机械跟票。'
    return '只使用个人视角与记忆，不要引用你不知道的信息。'


def _decode(data, req) -> ActionIntent:
    """把模型 JSON 转成已校验意图；结构或语义不合法时抛 ValueError。"""
    if not isinstance(data, dict) or set(data) - _OUTPUT_KEYS:
        raise ValueError('通用决策输出格式错误')
    if not isinstance(data.get('action'), str) or not isinstance(data.get('private_note', ''), str):
        raise ValueError('通用动作名或备注格式错误')
    intent = ActionIntent(req.instance_id, req.request_id, req.actor_id, req.state_version,
                          data['action'], data.get('arguments', {}), data.get('private_note', ''))
    req.validate(intent)
    return intent


def _retry_prompt(user: str, data, error: ValueError) -> str:
    """在原提示词后追加上次输出与错误，要求只修正到合法动作/参数。"""
    return (user + '\n\n上一次输出: '
            + json.dumps(data, ensure_ascii=False, default=str)
            + '\n该输出未通过校验: ' + str(error)
            + '\n请修正后重新输出。action 必须来自 allowed_actions；'
              '每个参数必须满足定义；不要输出额外字段。')


def decide_game(request_json, context):
    req = context.request
    packet = {'actor': req.actor_id, 'phase': req.phase, 'now': req.now, 'goal': req.goal,
              'view': req.view, 'instructions': req.instructions,
              'persona_traits': context.persona_traits,
              'persona_guidance': _persona_guidance(context.persona_traits),
              'phase_guidance': _phase_guidance(req.phase),
              'memories': context.memories,
              'allowed_actions': [asdict(a) for a in req.actions]}
    user = (json.dumps(packet, ensure_ascii=False, allow_nan=False) +
        '\n根据当前规则选择一个合法动作。只输出 JSON：'
        '{"action":"动作名","arguments":{参数},"private_note":"可选的简短私人策略备注"}。'
        '私人备注不会作为公开发言。历史原话只证明有人作出过该声明；不要把声明自动当作事实。')
    temperature = 0.7 if req.phase in ('speech', 'wolf_talk') else 0.2
    data = request_json(_SYSTEM, user, think=False, temperature=temperature,
                        _stats_tag='decide_game')
    try:
        return _decode(data, req)
    except ValueError as first_error:
        # 只对本地结构与语义校验失败重试；request_json 自身的异常不在此捕获。
        retry_user = _retry_prompt(user, data, first_error)
        retry_data = request_json(_SYSTEM, retry_user, think=False, temperature=0.0,
                                  _stats_tag='decide_game')
        try:
            return _decode(retry_data, req)
        except ValueError as second_error:
            raise ValueError(
                '通用决策两次输出均未通过校验: '
                f'{first_error}; {second_error}') from second_error
