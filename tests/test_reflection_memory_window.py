"""关系反思的 SQL 原料窗口及重要/近期混合候选。"""
import pytest

from game_agent import HashEmbedder, MemoryRecord, MemoryStore
from game_agent.memory.ranking import rank_memories
from game_agent.models.embeddings import cosine_similarity


class CountingEmbedder(HashEmbedder):
    def __init__(self):
        super().__init__()
        self.batches = []

    def embed(self, texts):
        self.batches.append(list(texts))
        return super().embed(texts)


def add(store, content, timestamp, player='P', importance=5, **options):
    return store.add(MemoryRecord(content, timestamp, player_id=player,
                                   importance=importance, **options))


def test_material_window_uses_time_not_insertion_and_filters_before_limit(monkeypatch):
    store = MemoryStore(HashEmbedder())
    try:
        for i in range(150):
            add(store, f'原料{i}', i)
        add(store, '乱序补录旧事', -1)
        add(store, '未来原料', 999)
        add(store, '另一玩家的新事', 150, 'Q')
        add(store, '共享的新事', 150, None)
        invalid = add(store, '已失效的新事', 150)
        store.invalidate(invalid)
        add(store, '不是观察', 150, type='reflection')
        def forbidden(*args, **kwargs):
            raise AssertionError('不能全量读取后切片')
        monkeypatch.setattr(store, 'all_valid', forbidden)
        recent = store.recent_relationship_observations('P', 200)
        assert [m.content for m in recent] == [f'原料{i}' for i in range(50, 150)]
        assert store.recent_relationship_observations('P', 200, limit=0) == []
        assert store.recent_relationship_observations('missing', 200) == []
        assert len(store.recent_relationship_observations('P', 200, limit=1000)) == 100
    finally:
        store.close()


def test_candidates_include_important_old_and_recent_without_full_embedding(monkeypatch):
    emb = CountingEmbedder()
    store = MemoryStore(emb)
    try:
        old = add(store, '很早的重要矿石事件', -100, importance=10)
        for i in range(200):
            add(store, f'矿石的普通经历{i}', i, importance=2)
        add(store, '其他关系重要矿石', 200, 'Q', importance=10)
        add(store, '共享重要矿石', 200, None, importance=10)
        add(store, '未来重要矿石', 999, importance=10)
        add(store, '类型不符矿石', 200, type='reflection', importance=10)
        invalid = add(store, '已失效重要矿石', 200, importance=10)
        store.invalidate(invalid)
        store._vec_cache.clear()
        emb.batches.clear()
        def forbidden(*args, **kwargs):
            raise AssertionError('有界取证不能读取整个关系流')
        monkeypatch.setattr(store, 'all_valid', forbidden)
        results = store.retrieve('矿石', 300, player_id='P', types=['observation'],
                                  candidate_limit=128, top_k=128, mark_accessed=False)
        assert len(results) == 128 and len({m['id'] for m in results}) == 128
        assert old in {m['id'] for m in results}
        assert all(m['player_id'] == 'P' and m['timestamp'] <= 300 and
                   m['type'] == 'observation' for m in results)
        assert [len(batch) for batch in emb.batches] == [1, 128]
        assert all(m.last_accessed is None for m in store._repository.all_valid())
        assert store.archive_count() == 206  # 原文不因窗口和失效被删除。
    finally:
        store.close()


def test_small_pool_uses_existing_absolute_importance_ranking_and_type_contract():
    emb = HashEmbedder()
    store = MemoryStore(emb)
    try:
        add(store, '旧矿石事件', 1, importance=9)
        add(store, '新矿石事件', 2, importance=2)
        add(store, '总结矿石', 2, type='episode')
        records = store.all_valid(player_id='P')
        scores = [cosine_similarity(v, emb.embed(['矿石'])[0]) for v in store.vectors(records)]
        expected = rank_memories(records, scores, 3, top_k=10, include_player='P')
        actual = store.retrieve('矿石', 3, player_id='P', include_player='P',
                               types=[], candidate_limit=128, mark_accessed=False)
        assert [(r['score'], r['id']) for r in actual] == [(score, r.id) for score, r in expected]
        episodes = store.retrieve('矿石', 3, player_id='P', types=['episode'],
                                  candidate_limit=128, mark_accessed=False)
        assert len(episodes) == 1 and episodes[0]['type'] == 'episode'
        assert store.count('P', types=['observation']) == 2
        assert store.count('P') == store.count('P', types=[]) == 3
    finally:
        store.close()


def test_equal_timestamps_have_stable_window_and_zero_candidates():
    store = MemoryStore(HashEmbedder())
    try:
        for i in range(5):
            add(store, str(i), 1)
        recent = store.recent_relationship_observations('P', 1, limit=2)
        assert [r.content for r in recent] == ['3', '4']
        assert store.retrieve('x', 1, player_id='P', candidate_limit=0) == []
    finally:
        store.close()


@pytest.mark.parametrize('options', [
    {}, {'player_id': 'P', 'shared': True},
    {'player_id': 'P', 'include_shared': True}, {'player_id': 'P', 'hearsay_only': True},
])
def test_bounded_candidates_cannot_silently_expand_scope(options):
    store = MemoryStore(HashEmbedder())
    try:
        with pytest.raises(ValueError, match='单一关系流'):
            store.retrieve('事件', 1, candidate_limit=128, **options)
    finally:
        store.close()
