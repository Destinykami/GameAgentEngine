"""用窄接口替身验证冲突组件的成本、隔离和失败重试契约。"""

from dataclasses import replace

import pytest

from game_agent.memory.models import MemoryRecord
from game_agent.cognition.reflection import ReflectionEngine
from game_agent.cognition.reflection.conflicts import ConflictResolver
from game_agent.cognition.reflection.policies import CONFLICT_CACHE_LIMIT


class ConflictRecords:
    """仅提供冲突处理需要的记忆方法，不继承 MemoryStore。"""

    def __init__(self, observations):
        self.reflection = MemoryRecord(
            content="Aria 值得信任", timestamp=0.0, type="reflection",
            player_id="Aria", id=1, confidence=0.8, base_confidence=0.8)
        self.observations = observations

    def all_valid(self, player_id=None, *, types=None, shared=False,
                  consolidated=None):
        records = [self.reflection, *self.observations]
        return [replace(record) for record in records
                if record.valid
                and (player_id is None or record.player_id == player_id)
                and (not shared or record.player_id is None)
                and (types is None or record.type in types)
                and (consolidated is None or record.consolidated == consolidated)]

    def invalidate(self, mem_id):
        assert mem_id == self.reflection.id
        self.reflection.valid = False

    def update_confidence(self, mem_id, confidence):
        assert mem_id == self.reflection.id
        self.reflection.confidence = confidence


class Judge:
    """只有矛盾判定能力，不继承 LLMClient。"""

    def __init__(self):
        self.calls = []
        self.fail_once = None

    def judge_conflict(self, reflection, observation):
        self.calls.append((reflection, observation))
        if observation == self.fail_once:
            self.fail_once = None
            raise RuntimeError("temporary model failure")
        return 0


def observation(index, content=None):
    return MemoryRecord(content=content or f"中性观察 {index}",
                        timestamp=float(index + 1), player_id="Aria")


def test_zero_severity_is_cached_and_resolvers_are_isolated():
    records = ConflictRecords([observation(0)])
    judge = Judge()
    first = ConflictResolver(judge)
    second = ConflictResolver(judge)
    assert first.check(records, "Aria", 2.0) == []
    assert first.check(records, "Aria", 3.0) == []
    assert len(judge.calls) == 1
    assert second.check(records, "Aria", 3.0) == []
    assert len(judge.calls) == 2
    assert records.reflection.confidence == 0.8


def test_failed_judgment_retries_without_discarding_successful_cache():
    records = ConflictRecords([observation(0), observation(1)])
    judge = Judge()
    judge.fail_once = records.observations[1].content
    resolver = ConflictResolver(judge)
    with pytest.raises(RuntimeError, match="temporary model failure"):
        resolver.check(records, "Aria", 3.0)
    assert records.reflection.confidence == 0.8
    assert resolver.check(records, "Aria", 4.0) == []
    assert [call[1] for call in judge.calls] == [
        records.observations[0].content, records.observations[1].content,
        records.observations[1].content,
    ]


def test_lru_bound_keeps_recent_hit_and_rechecks_evicted_pair():
    records = ConflictRecords([])
    judge = Judge()
    resolver = ConflictResolver(judge)

    def check(index):
        records.observations = [observation(index)]
        assert resolver.check(records, "Aria", 1000.0) == []

    for index in range(CONFLICT_CACHE_LIMIT):
        check(index)
    check(0)  # 命中必须刷新次序，插入下一条时应淘汰 1。
    check(CONFLICT_CACHE_LIMIT)
    check(0)
    assert len(judge.calls) == CONFLICT_CACHE_LIMIT + 1
    check(1)
    assert len(judge.calls) == CONFLICT_CACHE_LIMIT + 2


def test_heuristic_retains_older_evidence_beyond_llm_window():
    records = ConflictRecords([
        observation(0, "Aria 背叛了我"),
        *(observation(index) for index in range(1, 13)),
    ])
    judge = Judge()
    resolver = ConflictResolver(judge)
    assert resolver.check(records, "Aria", 20.0, policy="heuristic_decay") == [1]
    assert records.reflection.confidence == pytest.approx(0.4)
    assert records.reflection.valid
    assert judge.calls == []


def test_generation_uses_memory_port_and_updated_public_configuration():
    class MemoryPort:
        def __init__(self):
            self.records = [MemoryRecord(
                content="Aria 帮助了我", timestamp=0.0, id=5, player_id="Aria")]
            self.retrieval_options = None

        def recent_relationship_observations(self, player_id, now, *, limit=100):
            assert player_id == 'Aria' and now == 1.0 and limit == 100
            return self.records[:limit]

        def all_valid(self, player_id=None, *, types=None, shared=False,
                      consolidated=None):
            return [record for record in self.records
                    if (player_id is None or record.player_id == player_id)
                    and (not shared or record.player_id is None)
                    and (types is None or record.type in types)]

        def retrieve(self, query, now, **options):
            self.retrieval_options = options
            return [{"id": 5, "content": self.records[0].content}]

        def vectors(self, recs):
            raise AssertionError("No embedder was configured")

        def add(self, record):
            record.id = 6
            self.records.append(record)
            return record.id

    class Model:
        def reflection_questions(self, recent):
            return ["Aria 是否可靠?"]

        def reflection_insights(self, evidence, n=5):
            assert evidence == [(5, "Aria 帮助了我")]
            assert n == 3
            return [("Aria 值得信赖", [5, 9999])]

        def judge_conflict(self, reflection, observation):
            raise AssertionError("Generation must not trigger conflict checks")

    memory = MemoryPort()
    engine = ReflectionEngine(Model())
    engine.evidence_min_relevance = 0.6
    assert engine.reflect_relationship(memory, "Aria", 1.0) == [6]
    assert memory.retrieval_options["min_relevance"] == 0.6
    assert memory.retrieval_options["mark_accessed"] is False
    assert memory.retrieval_options['candidate_limit'] == 128
    assert memory.records[-1].evidence == [5]
    # 原始两个引用决定置信度，过滤幻影引用后仍保持原置信度。
    assert memory.records[-1].confidence == pytest.approx(0.7)
