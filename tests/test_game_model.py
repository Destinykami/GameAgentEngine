"""动态动作适配使用真实模型任务函数，但请求由离线替身承接。"""
from types import SimpleNamespace

import pytest

from game_agent.integration import ActionSpec, DecisionRequest, ParameterSpec
from game_agent.models.llm_http.game import decide_game


def test_dynamic_model_schema_and_invalid_output_have_no_space_fallback():
    request = DecisionRequest('g', 'r', 'A', '1', 'vote', 1, '获胜', '只有公开局势',
        (ActionSpec('vote', parameters=(ParameterSpec('target', choices=('B', 'C')),)),))
    context = SimpleNamespace(request=request, persona_traits={}, memories=())
    captured = {}
    def send(system, user, **options):
        captured.update(user=user, options=options)
        return {'action': 'vote', 'arguments': {'target': 'B'}, 'private_note': '策略'}
    result = decide_game(send, context)
    assert result.action == 'vote' and result.private_note == '策略'
    assert 'vote' in captured['user'] and '"move"' not in captured['user']
    assert '"now": 1' in captured['user']
    assert captured['options']['_stats_tag'] == 'decide_game'
    for response in ({'action': 'attack'}, {'action': 'vote', 'arguments': {'target': 'X'}},
                     {'action': 'vote', 'arguments': [], 'world': 'secret'}):
        with pytest.raises(ValueError):
            decide_game(lambda *a, **kw: response, context)
