"""终端与静态网页回放是只读输出，不启动模型或模拟。"""

import copy
import json
import sys

import pytest

from game_agent.runners.replay.cli import main
from game_agent.runners.replay.html import render_html
from game_agent.runners.replay import terminal


def timeline():
    step = {"day": 1, "moment": 7.5, "clock": 7.5, "events": ["<原始事件>"],
            "states": {"旅行者": {"health": 10, "loc": "城", "dead": False,
                                  "kind": "player", "reasons": ["实证"], "attack": 3}},
            "note": "<说明>", "decree_ended": False, "shogun_dead": False, "persuade": None}
    return {"reason_needed": None, "attack_needed": None, "persuade_n": None,
            "steps": [step, copy.deepcopy(step)]}


def test_replay_text_and_html_preserve_nullable_thresholds_and_escape_scope(monkeypatch, capsys):
    data = timeline()
    before = copy.deepcopy(data)
    delays = []
    monkeypatch.setattr(terminal.time, "sleep", delays.append)
    terminal.play_terminal(data, 1.5, False)
    assert delays == [1.5] and data == before
    assert "证据1条 攻3" in capsys.readouterr().out
    html = render_html(data)
    assert "&lt;原始事件&gt;" in html and "&lt;说明&gt;" in html
    assert "B+ 涌现" in html
    data.update(reason_needed=3, attack_needed=20, persuade_n=3)
    data["steps"][-1]["persuade"] = 1
    assert "理由1/3" in terminal.render_step(data["steps"][0], data)
    assert "双关" in render_html(data)


def test_replay_cli_writes_html_next_to_input_without_delay(tmp_path, monkeypatch, capsys):
    path = tmp_path / "timeline.json"
    path.write_text(json.dumps(timeline()), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["replay", "--file", str(path), "--no-delay", "--html"])
    assert main("unused.json") == 0
    assert (tmp_path / "replay.html").read_text() == render_html(timeline())
    assert "网页时间线已生成" in capsys.readouterr().out


def test_replay_empty_input_preserves_existing_error():
    with pytest.raises(IndexError):
        render_html({"steps": []})
