"""事件评分、关系取证及纯策略的边界和失败契约。"""

from dataclasses import replace

import pytest

from game_agent.cognition.reacting import ReactionDecider
from game_agent.cognition.reacting.policy import evaluate_response
from game_agent.cognition.reacting.scoring import EventScorer, EVENT_VALUE_CACHE_LIMIT
from game_agent.cognition.reacting.trust import RelationshipTrust
from game_agent.memory.models import MemoryRecord


class MemoryPort:
    def __init__(self, records=()):
        self.records = list(records)
        self.reads = []

    def all_valid(self, player_id):
        self.reads.append(player_id)
        return [replace(record) for record in self.records
                if record.valid and record.player_id == player_id]


def record(index, kind="observation", **options):
    return MemoryRecord(content=f"{kind}-{index}", timestamp=float(index),
                        type=kind, player_id="Aria", id=index + 1, **options)


def test_pure_policy_zero_threshold_and_original_trust_modulation():
    for trust, enabled, utility in ((0, True, 0), (-2, True, -2),
                                    (2, True, 4), (8, False, 0)):
        decision = evaluate_response("邀请", {}, (4, 0, 2), trust,
                                     use_relationship=enabled)
        assert decision.utility == utility
        assert decision.react is (utility >= 0)
    assert evaluate_response("邀请", {}, (4, 0, 2)).action == "接受并参与: 邀请"


def test_trust_window_order_hearsay_full_signature_and_instance_isolation():
    high = [record(i, ("reflection", "identity", "episode")[i % 3],
                   confidence=0.4, hearsay=i == 11, hop=2) for i in range(12)]
    for item in high:
        item.timestamp = 10.0  # 同时间必须按 id 降序。
        item.content = f"high-{item.id - 1}"
    observations = [record(i, importance=10.0 if i == 0 else 1.0)
                    for i in range(25)]
    plan = record(100, "plan")
    memory = MemoryPort([*high, *observations, plan])

    class Model:
        def __init__(self):
            self.calls = []

        def judge_trust(self, memories, player_id):
            self.calls.append((memories, player_id))
            return 0.25

    model = Model()
    trust = RelationshipTrust(memory, model)
    assert trust.get("Aria") == 0.25
    evidence, player = model.calls[0]
    assert player == "Aria"
    assert [text for _, text, _ in evidence[:10]] == [
        "[传闻2跳] high-11", *(f"high-{i}" for i in range(10, 1, -1))]
    assert [text for _, text, _ in evidence[10:]] == [
        f"observation-{i}" for i in range(24, 4, -1)]
    assert evidence[0] == ("episode", "[传闻2跳] high-11", 0.4)
    trust.get("Aria")
    assert len(model.calls) == 1
    plan.timestamp += 1  # 未入选的类型仍参与全量签名。
    trust.get("Aria")
    assert len(model.calls) == 2 and model.calls[0] == model.calls[1]
    other = RelationshipTrust(memory, model)
    other.get("Aria")
    assert len(model.calls) == 3
    trust.clear_cache()
    assert trust.cache_size == 0 and other.cache_size == 1


@pytest.mark.parametrize("kind,count", [("observation", 20), ("reflection", 10),
                                        ("plan", 0)])
def test_trust_pool_quotas_do_not_borrow_and_other_types_still_trigger_model(kind, count):
    class Model:
        def judge_trust(self, memories, player_id):
            assert len(memories) == count
            return 0.5

    trust = RelationshipTrust(MemoryPort(record(i, kind) for i in range(25)), Model())
    assert trust.get("Aria") == 0.5


def test_trust_neutral_empty_and_existing_signature_boundaries():
    class Model:
        calls = 0

        def judge_trust(self, memories, player_id):
            self.calls += 1
            return self.calls / 10

    memory = MemoryPort()
    model = Model()
    trust = RelationshipTrust(memory, model)
    assert trust.get(None) == 0.0 and memory.reads == []
    assert trust.get("Aria") == 0.0 and model.calls == 0
    memory.records.append(record(5))
    assert trust.get("Aria") == 0.1
    memory.records[0].confidence = 0.2
    memory.records[0].content = "原地修改内容"
    memory.records[0].importance = 1.0
    assert trust.get("Aria") == 0.1 and model.calls == 1
    memory.records.append(record(1, "plan"))
    assert trust.get("Aria") == 0.2 and model.calls == 2
    memory.records.clear()
    assert trust.get("Aria") == 0.0
    assert trust.cache_size == 1 and model.calls == 2


def test_event_lru_zero_values_persona_key_boundary_and_clear():
    class Model:
        calls = 0

        def score_event(self, event, persona_traits, current_plan=""):
            self.calls += 1
            return (0.0, 0.0, 0.0)

    model = Model()
    scorer = EventScorer(model)
    for index in range(EVENT_VALUE_CACHE_LIMIT):
        scorer.score(str(index), {}, "计划")
    scorer.score("0", {"social": 0.9}, "计划")
    scorer.score("新增", {}, "计划")
    scorer.score("0", {}, "计划")
    assert model.calls == EVENT_VALUE_CACHE_LIMIT + 1
    scorer.score("1", {}, "计划")
    assert model.calls == EVENT_VALUE_CACHE_LIMIT + 2
    assert scorer.cache_size == EVENT_VALUE_CACHE_LIMIT
    scorer.score("1", {}, "其他计划")
    assert model.calls == EVENT_VALUE_CACHE_LIMIT + 3
    scorer.clear_cache()
    assert scorer.cache_size == 0
    scorer.score("1", {}, "其他计划")
    assert model.calls == EVENT_VALUE_CACHE_LIMIT + 4


def test_score_model_failure_is_not_cached_and_precedes_relationship_read():
    class Model:
        calls = 0

        def score_event(self, *args):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("scoring failed")
            return (0, 0, 0)

    memory = MemoryPort()
    decider = ReactionDecider(memory, Model())
    with pytest.raises(RuntimeError, match="scoring failed"):
        decider.decide("事件", "Aria", {})
    assert memory.reads == []
    assert decider.cache_sizes() == {"events": 0, "trust": 0}
    assert decider.decide("事件", "Aria", {}).react


def test_trust_failure_keeps_successful_score_cache_and_clear_resets_both():
    class Model:
        def __init__(self):
            self.calls = []

        def score_event(self, *args):
            self.calls.append("score")
            return (2, 0, 0)

        def judge_trust(self, *args):
            self.calls.append("trust")
            if self.calls == ["score", "trust"]:
                raise RuntimeError("trust failed")
            return 0.5

    model = Model()
    decider = ReactionDecider(MemoryPort([record(1)]), model)
    with pytest.raises(RuntimeError, match="trust failed"):
        decider.decide("事件", "Aria", {})
    assert decider.cache_sizes() == {"events": 1, "trust": 0}
    assert decider.decide("事件", "Aria", {}).utility == 1.5
    assert model.calls == ["score", "trust", "trust"]
    sizes = decider.cache_sizes()
    sizes["events"] = 999
    assert decider.cache_sizes() == {"events": 1, "trust": 1}
    decider.clear_cache()
    assert decider.cache_sizes() == {"events": 0, "trust": 0}


def test_invalid_score_shape_stays_cached_without_reading_trust():
    class Model:
        calls = 0

        def score_event(self, *args):
            self.calls += 1
            return (1, 2)

    model = Model()
    memory = MemoryPort([record(1)])
    decider = ReactionDecider(memory, model)
    for _ in range(2):
        with pytest.raises(ValueError):
            decider.decide("事件", "Aria", {})
    assert model.calls == 1 and memory.reads == []
    assert decider.cache_sizes() == {"events": 1, "trust": 0}


def test_disabled_modulation_skips_trust_but_direct_query_remains_available():
    class Model:
        calls = 0

        def score_event(self, *args):
            return (0, 0, 0)

        def judge_trust(self, *args):
            self.calls += 1
            return 0.25

    memory = MemoryPort([record(1)])
    model = Model()
    decider = ReactionDecider(memory, model, use_relationship=False)
    assert decider.decide("事件", "Aria", {}).react
    assert memory.reads == [] and model.calls == 0
    assert decider.relationship_trust("Aria") == 0.25
    assert model.calls == 1
