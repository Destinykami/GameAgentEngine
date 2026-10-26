"""动态动作适配使用真实模型任务函数，但请求由离线替身承接。"""
from types import SimpleNamespace

import pytest

from game_agent.integration import ActionSpec, DecisionRequest, ParameterSpec
from game_agent.models.llm_http.game import decide_game


def _context():
    request = DecisionRequest('g', 'r', 'A', '1', 'vote', 1, '获胜', '只有公开局势',
        (ActionSpec('vote', parameters=(ParameterSpec('target', choices=('B', 'C')),)),))
    return SimpleNamespace(request=request, persona_traits={}, memories=())


def _replies(*responses):
    """按调用顺序返回预置输出；Exception 直接抛出。"""
    calls = []

    def send(system, user, **options):
        calls.append((system, user, options))
        response = responses[len(calls) - 1]
        if isinstance(response, Exception):
            raise response
        return response

    return send, calls


def test_dynamic_model_schema_and_invalid_output_have_no_space_fallback():
    captured = {}

    def send(system, user, **options):
        captured.update(user=user, options=options)
        return {'action': 'vote', 'arguments': {'target': 'B'}, 'private_note': '策略'}

    result = decide_game(send, _context())
    assert result.action == 'vote' and result.private_note == '策略'
    assert 'vote' in captured['user'] and '"move"' not in captured['user']
    assert '"now": 1' in captured['user']
    assert captured['options']['_stats_tag'] == 'decide_game'
    for response in ({'action': 'attack'}, {'action': 'vote', 'arguments': {'target': 'X'}},
                     {'action': 'vote', 'arguments': [], 'world': 'secret'}):
        send, calls = _replies(response, response)
        with pytest.raises(ValueError):
            decide_game(send, _context())
        assert len(calls) == 2


def test_invalid_output_is_retried_once_with_error_feedback():
    send, calls = _replies(
        {'action': 'vote', 'arguments': {'target': 'X'}},
        {'action': 'vote', 'arguments': {'target': 'B'}, 'private_note': '修正后'},
    )
    result = decide_game(send, _context())
    assert result.action == 'vote' and result.arguments == {'target': 'B'}
    assert len(calls) == 2
    assert '"X"' in calls[1][1]
    assert '不在合法选项中' in calls[1][1]
    assert calls[0][2]['temperature'] == 0.2
    assert calls[1][2]['temperature'] == 0.0
    assert all(call[2]['_stats_tag'] == 'decide_game' for call in calls)


def test_structural_failure_is_also_retried_once():
    send, calls = _replies(
        {'action': 'vote', 'arguments': {'target': 'B'}, 'world': 'secret'},
        {'action': 'vote', 'arguments': {'target': 'C'}},
    )
    result = decide_game(send, _context())
    assert result.arguments == {'target': 'C'}
    assert len(calls) == 2
    assert '格式错误' in calls[1][1]


def test_two_semantic_failures_raise_with_both_errors():
    send, calls = _replies(
        {'action': 'attack'},
        {'action': 'vote', 'arguments': {'target': 'X'}},
    )
    with pytest.raises(ValueError, match='两次输出均未通过校验') as error:
        decide_game(send, _context())
    assert len(calls) == 2
    message = str(error.value)
    assert '当前请求不允许此动作' in message
    assert '不在合法选项中' in message


def test_transport_or_json_error_is_not_semantically_retried():
    send, calls = _replies(ValueError('JSON 解析失败'))
    with pytest.raises(ValueError, match='JSON 解析失败'):
        decide_game(send, _context())
    assert len(calls) == 1
