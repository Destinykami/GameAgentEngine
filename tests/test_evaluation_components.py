"""评测口径、纯指标及公开世界查询的离线契约。"""

from types import SimpleNamespace
from pathlib import Path
import importlib
import runpy
import sys

import pytest

from game_agent import HashEmbedder, Location, MemoryRecord, World
from game_agent.evaluation.metrics import (
    context_contradiction, evidence_grounding, percentile, stale_recall, sum_usage,
)
from evals.baselines import FixedPriorityDecider
from evals.experiments import decision_ablation, memory_consistency
from evals.fixtures.decision import EVENTS, PERSONAS, TRUST_LEVELS
from tests.test_persistence import _StubLLM


class Store:
    def __init__(self):
        self.valid = [MemoryRecord("原始观察", 0, id=1),
                      MemoryRecord("无证据", 1, type="reflection", player_id="P", id=2),
                      MemoryRecord("级联", 2, type="reflection", player_id="P", id=3, evidence=[2])]
        self.invalid = [MemoryRecord("有据", 3, type="reflection", player_id="P", id=4,
                                     evidence=[1], valid=False)]
        self.calls = []

    def all_valid(self, player_id=None, types=None):
        return [m for m in self.valid if (player_id is None or m.player_id == player_id)
                and (types is None or m.type in types)]

    def all_invalid(self):
        return self.invalid

    def retrieve(self, **options):
        self.calls.append(options)
        return [{"id": 2}, {"id": 1}]


def test_grounding_counts_invalid_refs_and_retains_empty_evidence_denominator():
    store = Store()
    assert evidence_grounding(store, "P") == {"reflections": 3, "grounded": 1,
                                               "cascaded": 1, "egr": 1/3}
    assert evidence_grounding(store, "unknown")["egr"] == 1


def test_recall_and_context_conflict_keep_retrieval_parameters_and_empty_shape():
    store = Store()
    empty = stale_recall(store, "查询", 10, [], "P")
    assert empty["stale_total"] == 0 and "stale_avg_rank" not in empty
    assert store.calls == []
    recall = stale_recall(store, "查询", 10, [2, 3], "P")
    assert recall["stale_ranks"] == [1] and recall["stale_fraction"] == 0.5
    assert store.calls[-1] == {"query": "查询", "now": 10, "player_id": "P",
                               "top_k": 8, "include_player": "P"}
    assert context_contradiction(store, "查询", 10, "P", [2], [1])
    assert not context_contradiction(store, "查询", 10, "P", [3], [1])
    before = len(store.calls)
    assert not context_contradiction(store, "查询", 10, "P", [], [1])
    assert len(store.calls) == before


@pytest.mark.parametrize("values,p,expected", [([], .5, 0), ([3], .95, 3),
                                              ([3, 1, 2], .5, 2), ([0, 10], .95, 9.5)])
def test_percentile_preserves_linear_interpolation(values, p, expected):
    assert percentile(values, p) == expected


def test_usage_aggregates_instances_without_latency_or_mutating_source():
    stats = {"calls": 2, "prompt_tokens": 7, "completion_tokens": 3,
             "by_method": {"ask": {"calls": 2, "prompt_tokens": 7, "completion_tokens": 3}}}
    result = sum_usage({"A": SimpleNamespace(stats=stats), "B": SimpleNamespace(stats=stats)})
    assert result["calls"] == 4 and result["by_method"]["ask"]["prompt_tokens"] == 14
    assert "total_latency_s" not in result and stats["calls"] == 2


def test_fixed_priority_matrix_is_independent_of_persona_and_trust():
    decider = FixedPriorityDecider()
    for event in EVENTS.values():
        results = [decider.decide(event["text"], trust, persona["traits"])
                   for persona in PERSONAS.values() for trust in TRUST_LEVELS]
        assert all(d == results[0] for d in results)
    assert decider.decide("威胁并请求帮助", "P", {}).utility == 99
    assert not decider.decide("继续工作", "P", {}).react


def test_trials_accept_offline_factories_and_judges(monkeypatch):
    models = []

    def model():
        instance = _StubLLM()
        models.append(instance)
        return instance

    monkeypatch.setattr(decision_ablation, "fresh_llm", model)
    trial = decision_ablation.run_scenario("no_relationship", "social", "high", HashEmbedder())
    assert trial["method"] == "no_relationship" and len(trial["events"]) == 6
    judge = SimpleNamespace(ask=lambda *args, **kw: "NO")
    record = memory_consistency.run_trajectory(memory_consistency.ARMS["ours"],
        memory_consistency.TRAJECTORIES[0], model(), HashEmbedder(), judge)
    assert not record["utterance_contradiction"] and record["player"] == "Aria"


def test_npc_name_snapshot_keeps_registration_order_and_cannot_mutate_registry(tmp_path):
    world = World("世界", [Location("L", 0, 0)])
    try:
        world.add_npc("B", {}, _StubLLM(), data_dir=str(tmp_path))
        before = world.npc_names()
        world.add_npc("A", {}, _StubLLM(), data_dir=str(tmp_path))
        assert before == ("B",) and world.npc_names() == ("B", "A")
        assert world.npc("B").name == "B"
    finally:
        world.close()


@pytest.mark.parametrize("name", ["memory_consistency", "decision_ablation", "scheduling_efficiency"])
def test_cli_dispatch_preserves_executable_entry_without_online_run(name, monkeypatch):
    module = importlib.import_module("evals.experiments." + name)
    calls = []
    monkeypatch.setattr(module, "main", lambda: calls.append(name) or 0)
    monkeypatch.setattr(sys, "path", list(sys.path))
    path = Path(__file__).resolve().parents[1] / "evals" / (name + ".py")
    with pytest.raises(SystemExit) as stopped:
        runpy.run_path(str(path), run_name="__main__")
    assert stopped.value.code == 0 and calls == [name]
