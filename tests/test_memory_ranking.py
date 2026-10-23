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
