"""场景裁决、结束条件与运行产物协议，全部使用离线依赖。"""

import json
from types import SimpleNamespace

import pytest

from game_agent import HashEmbedder, Location, World
from game_agent.runners.artifacts import RunPaths, TimelineWriter, reset_directory
from game_agent.runners.inazuma import run
from game_agent.scenarios.inazuma.judgment import _judge_shogun
from game_agent.scenarios.inazuma.outcome import resolve_outcome
from tests.test_persistence import _StubLLM


def test_timeline_writer_overwrites_stream_flushes_each_step_and_matches_final(tmp_path):
    live = tmp_path / "live.jsonl"
    live.write_text("旧数据\n")
    meta = {"schema_version": 1, "world": {"name": "世界"}, "reason_needed": None}
    writer = TimelineWriter(str(live), meta)
    assert json.loads(live.read_text()) == {"__meta__": True, **meta}
    step = {"clock": 1, "states": {}, "visual_events": [], "note": "中文"}
    writer.append(step)
    assert json.loads(live.read_text().splitlines()[1]) == step
    flags = {"decree_ended": False, "shogun_dead": False}
    writer.finish(flags)
    writer.write_final(str(tmp_path / "timeline.json"), meta)
    assert json.loads(live.read_text().splitlines()[-1]) == {"__done__": True, **flags}
    assert json.loads((tmp_path / "timeline.json").read_text()) == {**meta, "steps": [step]}
    assert live.read_text().endswith("\n") and "中文" in live.read_text()


def test_run_directory_reset_only_affects_explicit_path(tmp_path):
    target = tmp_path / "run"
    target.mkdir()
    (target / "old").write_text("旧运行")
    sibling = tmp_path / "sibling"
    sibling.write_text("保留")
    reset_directory(str(target))
    assert list(target.iterdir()) == [] and sibling.read_text() == "保留"
    assert RunPaths(str(target), "live.jsonl").timeline_path == str(target / "timeline.json")


@pytest.mark.parametrize("raw,expected", [
    ('```json\n{"revoked":true,"reason":"证据充分"}\n```', (True, "证据充分")),
    ('前文 {"revoked":false} 后文', (False, "")),
    ('{"revoked":"false","reason":3}', (True, "3")),
    ('bad-json', (False, "")), ('{}', (False, "")),
])
def test_judgment_preserves_parsing_and_original_truthiness(raw, expected):
    calls = []

    def ask(prompt, **options):
        calls.append((prompt, options))
        return raw

    shogun = SimpleNamespace(goal="维护秩序")
    traveler = SimpleNamespace(reasons=["实证"])
    assert _judge_shogun(SimpleNamespace(ask=ask), shogun, traveler, "陈述", "答复") == expected
    assert "实证" in calls[0][0] and "维护秩序" in calls[0][0]
    assert calls[0][1]["max_tokens"] == 200


def test_judgment_failure_is_conservative():
    def fail(*args, **kwargs):
        raise RuntimeError("offline")

    shogun, traveler = SimpleNamespace(goal="秩序"), SimpleNamespace(reasons=[])
    assert _judge_shogun(None, shogun, traveler, "", "") == (False, "")
    assert _judge_shogun(SimpleNamespace(ask=fail), shogun, traveler, "", "") == (False, "")


def outcome_world(dead=False):
    traveler = SimpleNamespace(reasons=[], history=[])
    traveler.record = traveler.history.append
    shogun = SimpleNamespace(dead=dead, goal="秩序")
    entities = {"旅行者": traveler, "雷电将军": shogun}
    events = []
    world = SimpleNamespace(get=entities.get, visual_events=[
        SimpleNamespace(type="conversation", actor="旅行者", target="雷电将军", reply="首个回复")],
        world_event=lambda description, now: events.append((description, now)))
    return world, traveler, events


def test_outcome_death_precedes_judgment_and_rejection_feedback(capsys):
    world, traveler, events = outcome_world(True)
    note, ended = resolve_outcome(world, object(), {}, 7)
    assert ended and "阵亡" in note and events == [] and traveler.history == []
    world, traveler, events = outcome_world()
    decisions = {"旅行者": {"action": "talk", "target": "雷电将军", "utterance": "陈述"}}
    note, ended = resolve_outcome(world, None, decisions, 8)
    assert not ended and "尚未被说服" in note and len(traveler.history) == 1
    model = SimpleNamespace(ask=lambda *a, **kw: '{"revoked":true,"reason":"实证"}')
    note, ended = resolve_outcome(world, model, decisions, 9)
    assert ended and "实证" in note and events[0][1] == 9
    assert len(traveler.history) == 1


def test_world_agent_model_query_tracks_public_registration():
    world = World("世界", [Location("L", 0, 0)])
    try:
        world.add_player("P", "L")
        assert world.agent_model("P") is None and world.agent_model("unknown") is None
        first, second = object(), object()
        world.register_agent("P", first)
        assert world.agent_model("P") is first
        world.register_agent("P", second)
        assert world.agent_model("P") is second
    finally:
        world.close()


def test_autonomous_runner_with_offline_factories_produces_readable_artifacts(tmp_path, capsys):
    data = tmp_path / "run"
    paths = RunPaths(str(data), str(tmp_path / "live.jsonl"))
    assert run(paths, llm_factory=_StubLLM, embedder_factory=HashEmbedder,
               days=1, moments=[7]) == 0
    timeline = json.loads((data / "timeline.json").read_text())
    live = [json.loads(line) for line in (tmp_path / "live.jsonl").read_text().splitlines()]
    assert len(timeline["steps"]) == 2 and timeline["steps"][0]["day"] == 0
    assert live[1:-1] == timeline["steps"]
    assert live[0]["__meta__"] and live[-1]["__done__"]
    assert timeline["reason_needed"] is None and timeline["persuade_n"] is None
    assert len(timeline["steps"][0]["states"]) == 6
    assert (data / "world.db").exists() and (data / "桃音.db").exists()
