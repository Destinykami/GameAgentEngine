"""独立排序契约：保留过滤顺序、折扣顺序、稳定截断及无访问副作用。"""

from dataclasses import asdict

import pytest

from game_agent.memory.models import MemoryRecord
from game_agent.memory.ranking import rank_memories


def test_confidence_and_hearsay_discount_precede_relationship_bonus():
    rec = MemoryRecord("传闻", 0.0, importance=6.0, player_id="P",
                       confidence=0.5, hearsay=True, hop=2, id=1)
    before = asdict(rec)
    ranked = rank_memories([rec], [0.8], 10.0, include_player="P")
    assert ranked[0][0] == pytest.approx((1.0 + 0.6 + 1.0) * 0.5 * 0.8**2 + 0.5)
    assert ranked[0][1] is rec
    assert asdict(rec) == before


def test_recency_and_relevance_normalize_after_relevance_filter():
    records = [MemoryRecord(f"记忆{i}", float(i), importance=5.0, id=i)
               for i in range(1, 4)]
    ranked = rank_memories(records, [0.2, 0.3, 0.4], 10.0, min_relevance=0.25)
    assert [rec.id for _, rec in ranked] == [3, 2]
    assert [score for score, _ in ranked] == pytest.approx([2.5, 0.5])


def test_equal_scores_keep_candidate_order_when_truncated():
    records = [MemoryRecord(f"记忆{i}", 0.0, id=i) for i in range(3)]
    ranked = rank_memories(records, [0.7, 0.7, 0.7], 10.0, top_k=2)
    assert [rec.id for _, rec in ranked] == [0, 1]
    assert [rec.last_accessed for rec in records] == [None, None, None]


def test_store_retrieve_can_use_relevance_only_weights():
    from game_agent.memory import MemoryStore
    from game_agent.models.embeddings import HashEmbedder

    store = MemoryStore(HashEmbedder())
    try:
        store.add(MemoryRecord('red bicycle', 0.0, importance=1.0))
        store.add(MemoryRecord('blue car', 1000.0, importance=10.0))
        default = store.retrieve('red bicycle', now=1001.0, top_k=2,
                                 mark_accessed=False)
        relevant = store.retrieve('red bicycle', now=1001.0, top_k=2,
                                  mark_accessed=False, weights=(0.0, 0.0, 1.0))
        assert [row['content'] for row in default] == ['blue car', 'red bicycle']
        assert [row['content'] for row in relevant] == ['red bicycle', 'blue car']
    finally:
        store.close()


@pytest.mark.parametrize('weights', [(1.0, 2.0), (-1.0, 0.0, 1.0),
                                    (float('nan'), 0.0, 1.0),
                                    (True, 0.0, 1.0)])
def test_store_retrieve_rejects_invalid_weights(weights):
    from game_agent.memory import MemoryStore
    from game_agent.models.embeddings import HashEmbedder

    store = MemoryStore(HashEmbedder())
    try:
        with pytest.raises(ValueError):
            store.retrieve('x', now=0.0, weights=weights)
    finally:
        store.close()
