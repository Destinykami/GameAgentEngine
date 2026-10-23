"""绝对重要性：相同新近性与相关性下，分数保留 importance/10 的量纲。"""

import pytest

from persona_agent import MemoryRecord, MemoryStore
from persona_agent.embeddings import Embedder


class _ConstantEmbedder(Embedder):
    @property
    def dim(self):
        return 2

    def embed(self, texts):
        return [[1.0, 0.0] for _ in texts]


@pytest.fixture
def store():
    memory = MemoryStore(_ConstantEmbedder())
    yield memory
    memory.close()


def _scores(store):
    return {m["id"]: m["score"] for m in
            store.retrieve("固定查询", now=0.0, mark_accessed=False)}


@pytest.mark.parametrize("importance", [1.5, 5.0, 6.0, 10.0])
def test_single_candidate_preserves_absolute_importance(store, importance):
    mid = store.add(MemoryRecord("单条记忆", 0.0, importance=importance))
    assert _scores(store)[mid] == pytest.approx(2.0 + importance / 10.0)


def test_other_candidate_importance_does_not_rescale_existing_score(store):
    original = store.add(MemoryRecord("记忆甲", 0.0, importance=5.0))
    before = _scores(store)[original]
    added = store.add(MemoryRecord("记忆乙", 0.0, importance=6.0))
    scores = _scores(store)
    assert scores[original] == pytest.approx(before)
    assert scores[original] == pytest.approx(2.5)
    assert scores[added] == pytest.approx(2.6)


def test_equal_importance_does_not_become_full_importance(store):
    for content in ("记忆甲", "记忆乙"):
        store.add(MemoryRecord(content, 0.0, importance=5.0))
    assert list(_scores(store).values()) == pytest.approx([2.5, 2.5])


def test_min_score_uses_absolute_importance(store):
    store.add(MemoryRecord("重要性为六", 0.0, importance=6.0))
    assert store.retrieve("固定查询", now=0.0, min_score=2.7) == []
    assert store.all_valid()[0].last_accessed is None


def test_forgetting_lowers_score_even_with_one_candidate(store):
    mid = store.add(MemoryRecord("将会淡化的记忆", 0.0, importance=8.0))
    assert _scores(store)[mid] == pytest.approx(2.8)
    store.decay_and_forget(48.0)
    hits = store.retrieve("固定查询", now=48.0, mark_accessed=False)
    assert hits[0]["importance"] == pytest.approx(4.0)
    assert hits[0]["score"] == pytest.approx(2.4)
