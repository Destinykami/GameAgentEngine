"""动态动作决策；游戏规则与动作说明仅来自已筛选的请求。"""
from dataclasses import asdict
import json

from ...integration.contracts import ActionIntent


def decide_game(request_json, context):
    req = context.request
    packet = {'actor': req.actor_id, 'phase': req.phase, 'goal': req.goal,
              'view': req.view, 'instructions': req.instructions,
              'persona_traits': context.persona_traits, 'memories': context.memories,
              'allowed_actions': [asdict(a) for a in req.actions]}
    user = (json.dumps(packet, ensure_ascii=False, allow_nan=False) +
        '\n根据当前规则选择一个合法动作。只输出 JSON：'
        '{"action":"动作名","arguments":{参数},"private_note":"可选的简短私人策略备注"}。'
        '私人备注不会作为公开发言。历史原话只证明有人作出过该声明；不要把声明自动当作事实。')
    data = request_json('你是游戏 NPC 决策器。只使用提供的个人视角和记忆，遵守当前游戏规则。',
        user, think=False, temperature=0.2, _stats_tag='decide_game')
    if not isinstance(data, dict) or set(data) - {'action', 'arguments', 'private_note'}:
        raise ValueError('通用决策输出格式错误')
    if not isinstance(data.get('action'), str) or not isinstance(data.get('private_note', ''), str):
        raise ValueError('通用动作名或备注格式错误')
    intent = ActionIntent(req.instance_id, req.request_id, req.actor_id, req.state_version,
                          data['action'], data.get('arguments', {}), data.get('private_note', ''))
    req.validate(intent)
    return intent
