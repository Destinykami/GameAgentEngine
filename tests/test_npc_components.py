"""NPC 子组件的窄端口、状态隔离及失败顺序契约。"""

from dataclasses import replace
from types import SimpleNamespace

import pytest

from game_agent import MemoryRecord, NPC
from game_agent.cognition.npc.consolidation import consolidate_observations
from game_agent.cognition.npc.observation import describe_action, write_observation
from game_agent.cognition.npc.persistence import (
    load_configuration, restore_runtime, save_checkpoint,
)
from game_agent.cognition.npc.reactions import ReactionCache
from game_agent.cognition.npc.state import RuntimeState
from game_agent.cognition.planning.state import PlanState
from game_agent.cognition.reacting.policy import ReactionDecision
from tests.test_persistence import _StubLLM, TRAITS


def test_clock_out_of_order_sweep_failure_and_snapshot_isolation():
    state = RuntimeState()
    calls = []
    state.advance(10, calls.append)
    state.advance(4, calls.append)
    assert state.game_time == 10 and state.last_sweep == 10 and calls == []

    def fail(now):
        calls.append(now)
        raise RuntimeError("sweep")

    with pytest.raises(RuntimeError, match="sweep"):
        state.advance(16, fail)
    assert state.game_time == 16 and state.last_sweep == 10
    state.advance(16, calls.append)
    assert calls == [16, 16] and state.last_sweep == 16
    state.reflected_obs["P"] = 3
    snapshot = state.snapshot()
    snapshot.reflected_obs["P"] = 99
    snapshot.game_time = -1
    assert state.reflected_obs == {"P": 3} and state.game_time == 16
    assert RuntimeState().reflected_obs == {}


def test_observation_write_ports_deduplicate_before_scoring_and_preserve_source():
    calls = []

    class Store:
        duplicate = None

        def find_similar_observation(self, content, player_id):
            calls.append(("find", content, player_id))
            return self.duplicate

        def merge_observation(self, memory_id, now, **options):
            calls.append(("merge", memory_id, now, options))
            return 9.0

        def add(self, record):
            calls.append(("add", record))
            return 7

    class Model:
        def score_importance(self, content, player_id):
            calls.append(("score", content, player_id))
            return 5.0

    store = Store()
    result = write_observation(store, Model(), "传闻", 1, "P", True, 2)
    assert result.created and result.memory_id == 7 and result.importance == 5
    assert [call[0] for call in calls] == ["find", "score", "add"]
    assert calls[-1][1].hearsay and calls[-1][1].hop == 2
    calls.clear()
    store.duplicate = MemoryRecord("旧传闻", 0, id=7)
    result = write_observation(store, object(), "亲见", 2, "P", False, 0)
    assert not result.created and result.memory_id == 7
    assert calls == [("find", "亲见", "P"),
                     ("merge", 7, 2, {"new_hearsay": False, "new_hop": 0,
                                        "new_content": "亲见"})]
    calls.clear()
    store.duplicate = None
    assert write_observation(store, object(), "预打分", 3, importance=0).importance == 0
    assert [call[0] for call in calls] == ["find", "add"]


def test_action_description_only_needs_relation_reader_and_perception_model():
    class Store:
        def all_valid(self, **filters):
            assert filters == {"player_id": "P", "types": ["observation"]}
            return [MemoryRecord(str(i), -i) for i in range(5)]

    class Model:
        def perceive_action(self, name, player, action, context):
            assert (name, player, action, context) == ("N", "P", "帮助", "2 | 3 | 4")
            return "生成观察"

    assert describe_action(Store(), Model(), "N", "P", "帮助") == "生成观察"


class EpisodeStore:
    def __init__(self, records, fail=None):
        self.records = records
        self.calls = []
        self.fail = fail

    def all_valid(self, player_id=None, types=None, shared=False, consolidated=None):
        return [replace(m) for m in self.records if m.valid
                and (types is None or m.type in types)
                and (not shared or m.player_id is None)
                and (player_id is None or m.player_id == player_id)
                and (consolidated is None or m.consolidated == consolidated)]

    def add(self, record):
        self.calls.append(("add", record.player_id))
        if self.fail == "add":
            raise RuntimeError("add")
        record.id = len(self.records) + 1
        self.records.append(record)
        return record.id

    def mark_consolidated(self, ids):
        self.calls.append(("mark", ids))
        if self.fail == "mark":
            raise RuntimeError("mark")
        for m in self.records:
            if m.id in ids:
                m.consolidated = True


def episode_records():
    return [MemoryRecord(f"{pid}-{i}", timestamp=t, player_id=pid, id=index,
                         confidence=0.4 if i == 0 else 0.8,
                         importance=3 if i == 0 else 8, hearsay=i == 0, hop=2)
            for index, (pid, i, t) in enumerate(
                [(pid, i, t) for pid in ("B", None, "A")
                 for i, t in enumerate((1, 25))], start=1)]


def test_consolidation_stream_order_window_boundary_future_and_source_fields():
    store = EpisodeStore(episode_records())
    store.records += [MemoryRecord("窗口外", -0.1, id=7),
                      MemoryRecord("未来观察", 100, id=8)]
    calls = []

    class Model:
        def consolidate_observations(self, observations, player_id):
            calls.append((player_id, observations))
            return "  情节  "

    ids = consolidate_observations(store, Model(), 24)
    assert len(ids) == 3
    assert [pid for pid, _ in calls] == [None, "A", "B"]
    assert calls[0][1] == ["None-0", "None-1", "未来观察"]
    episodes = [m for m in store.records if m.type == "episode"]
    assert all(m.content == "情节" and m.confidence == m.base_confidence == 0.4
               and m.importance == 8 and m.hearsay and m.hop == 2 for m in episodes)
    assert episodes[0].evidence == [3, 4, 8]
    assert not store.records[6].consolidated  # 窗口外观察不吸收。
    assert consolidate_observations(store, Model(), 24) == []


@pytest.mark.parametrize("failure", ["model", "add", "mark"])
def test_consolidation_failure_retains_original_partial_write_order(failure):
    store = EpisodeStore(episode_records(), fail=failure)

    class Model:
        def consolidate_observations(self, observations, player_id):
            if failure == "model":
                raise RuntimeError("model")
            return "摘要"

    with pytest.raises(RuntimeError, match=failure):
        consolidate_observations(store, Model(), 24)
    episodes = [m for m in store.records if m.type == "episode"]
    assert len(episodes) == (1 if failure == "mark" else 0)
    assert not any(m.consolidated for m in store.records)
    assert [kind for kind, _ in store.calls] == {
        "model": [], "add": ["add"], "mark": ["add", "mark"]}[failure]


def test_partial_batch_skips_npc_conflict_hook_and_retries_only_remaining_streams(monkeypatch):
    class Model(_StubLLM):
        fail = True

        def consolidate_observations(self, observations, player_id):
            if player_id == "A" and self.fail:
                raise RuntimeError("later stream")
            return "摘要"

    model = Model()
    npc = NPC("N", {}, model)
    for record in episode_records():
        npc.store.add(record)
    conflicts = []
    monkeypatch.setattr(npc, "check_shared_conflicts", conflicts.append)
    try:
        with pytest.raises(RuntimeError, match="later stream"):
            npc.consolidate(24)
        assert [m.player_id for m in npc.store.all_valid(types=["episode"])] == [None]
        assert conflicts == [] and npc.game_time == 24
        model.fail = False
        assert len(npc.consolidate(24)) == 2
        assert conflicts == [24]
    finally:
        npc.store.close()


def test_blank_summary_does_not_write_or_mark_sources():
    store = EpisodeStore(episode_records())
    model = SimpleNamespace(consolidate_observations=lambda obs, pid: " \n ")
    assert consolidate_observations(store, model, 24) == []
    assert store.calls == [] and not any(m.consolidated for m in store.records)


def test_npc_reflection_failure_watermarks_and_shared_claim_order(monkeypatch):
    npc = NPC("N", {}, _StubLLM(), reflection_threshold=5)
    npc.observe("共享观察", 1, importance=5)
    npc.observe("关系观察", 1, "P", importance=5)
    calls = []
    failure = {"self": True, "conflict": False}

    def reflect_self(store, now):
        calls.append("self")
        if failure["self"]:
            raise RuntimeError("self")
        return [7]

    def check_conflicts(store, player, now, **options):
        calls.append(("conflict", player))
        if failure["conflict"]:
            raise RuntimeError("conflict")
        return []

    npc.reflection = SimpleNamespace(reflect_self=reflect_self,
        reflect_relationship=lambda store, player, now: [8], check_conflicts=check_conflicts)
    try:
        with pytest.raises(RuntimeError, match="self"):
            npc.maybe_reflect_self(2)
        assert npc.runtime_state().importance_accum == 5 and npc.game_time == 1
        failure.update(self=False, conflict=True)
        with pytest.raises(RuntimeError, match="conflict"):
            npc.maybe_reflect_self(2)
        assert npc.runtime_state().importance_accum == 0
        assert npc.runtime_state().shared_conflict_sig == (1, 1)
        assert npc.check_shared_conflicts(2) == []  # 原签名在失败后仍命中。
        with pytest.raises(RuntimeError, match="conflict"):
            npc.maybe_reflect_relationship("P", 3)
        assert npc.runtime_state().reflected_obs == {} and npc.game_time == 3
        failure["conflict"] = False
        assert npc.maybe_reflect_relationship("P", 4) == [8]
        assert npc.runtime_state().reflected_obs == {"P": 1}
        assert npc.maybe_reflect_relationship("P", 8) == [] and npc.game_time == 4
        snapshot = npc.runtime_state()
        snapshot.reflected_obs.clear()
        snapshot.importance_accum = 99
        assert npc.runtime_state().reflected_obs == {"P": 1}
        assert npc.runtime_state().importance_accum == 0
    finally:
        npc.store.close()


def test_reaction_cache_rechecks_trust_on_hit_and_write_gate_after_decision():
    cache = ReactionCache()
    calls = []
    enabled = [True]

    class Decider:
        use_relationship = True

        def relationship_trust(self, player):
            calls.append("trust")
            return 0.1

        def decide(self, *args):
            calls.append("decide")
            return ReactionDecision(False, "婉拒接受邀请", -2, "原始原因")

    decider = Decider()
    first = cache.decide(decider, "event", "P", {}, "a" * 21, lambda: enabled[0])
    enabled[0] = False
    second = cache.decide(decider, "event", "P", {}, "a" * 21, lambda: enabled[0])
    assert second.action == first.action and second.utility == first.utility
    assert second.reason == "决策缓存命中" and calls == ["trust", "decide", "trust"]
    cache.clear()

    def switch_tier(*args):
        enabled[0] = False
        return first

    enabled[0] = True
    decider.decide = switch_tier
    cache.decide(decider, "event", "P", {}, "", lambda: enabled[0])
    assert cache.size == 0


def test_npc_cache_clear_order_and_diagnostic_isolation(monkeypatch):
    npc = NPC("N", dict(TRAITS), _StubLLM())
    try:
        npc.observe("P 帮助我", 0, "P")
        npc.react("邀请", "P", 1)
        assert npc.cache_sizes() == {"decisions": 1, "events": 1, "trust": 1}
        sizes = npc.cache_sizes()
        sizes.clear()
        assert npc.cache_sizes()["decisions"] == 1
        clear = npc.decider.clear_cache

        def clear_decider():
            assert npc.cache_sizes()["decisions"] == 0
            clear()

        monkeypatch.setattr(npc.decider, "clear_cache", clear_decider)
        npc.clear_cache()
        assert npc.cache_sizes() == {"decisions": 0, "events": 0, "trust": 0}
    finally:
        npc.store.close()


class MetadataPort:
    def __init__(self, meta=None, fail=None):
        self.meta = dict(meta or {})
        self.calls = []
        self.fail = fail

    def is_persistent(self):
        return True

    def get_meta(self, key, default=None):
        self.calls.append(("get", key))
        return self.meta.get(key, default)

    def set_meta(self, key, value):
        self.calls.append(("set", key))
        if key == self.fail:
            raise RuntimeError("metadata write")
        self.meta[key] = value

    def db_path(self):
        return "npc.db"


def test_metadata_defaults_threshold_override_and_runtime_restore_scope():
    port = MetadataPort({"npc": {"name": "N", "persona_traits": {},
                                  "reflection_threshold": 7},
                         "game_time": "12.5", "reflected_obs": {2: "3"},
                         "plan_blocks": [[7.5, 9.5, "工作"], ["bad", 2, "跳过"]]})
    assert load_configuration(port, "npc.db", None)[1] == 7
    assert load_configuration(port, "npc.db", 0)[1] == 0
    state = RuntimeState()
    plans = restore_runtime(port, state)
    assert state.game_time == state.last_sweep == 12.5
    assert state.reflected_obs == {"2": 3}
    assert plans.blocks == [(7, 9, "工作")] and plans.interruption == ""
    assert state.tier == "full" and state.importance_accum == 0
    assert state.shared_conflict_sig is None
    legacy = MetadataPort({"npc": {"name": "N", "persona_traits": {}}})
    assert load_configuration(legacy, "legacy.db", None)[1] == 150
    assert restore_runtime(legacy, RuntimeState()).blocks == []


def test_metadata_save_partial_failure_keeps_key_order_and_delays_path_update():
    port = MetadataPort(fail="reflected_obs")
    state = RuntimeState(game_time=12, reflected_obs={"P": 3})
    plans = PlanState([(7, 9, "工作")], interruption="不持久化")
    with pytest.raises(RuntimeError, match="metadata write"):
        save_checkpoint(port, "N", {}, state, plans)
    assert [key for _, key in port.calls] == ["npc", "game_time", "reflected_obs"]
    assert set(port.meta) == {"npc", "game_time"} and state.data_path is None
    port.fail = None
    save_checkpoint(port, "N", {}, state, plans)
    assert set(port.meta) == {"npc", "game_time", "reflected_obs", "plan_blocks"}
    assert port.meta["plan_blocks"] == [[7, 9, "工作"]] and state.data_path == "npc.db"
    state.reflected_obs["P"] = 99
    assert port.meta["reflected_obs"] == {"P": 3}


def test_reaction_cache_uses_entire_plan_and_structured_event_player_key():
    cache = ReactionCache()
    class Decider:
        use_relationship = False
        calls = 0
        def decide(self, *args):
            self.calls += 1
            return ReactionDecision(True, str(self.calls), self.calls, "new")
    decider = Decider()
    for event, player, plan in [("e|P", "Q", "a" * 21),
                                ("e|P", "Q", "a" * 20 + "b"),
                                ("e", "P|Q", "a" * 21)]:
        cache.decide(decider, event, player, {}, plan, lambda: True)
    assert decider.calls == 3
