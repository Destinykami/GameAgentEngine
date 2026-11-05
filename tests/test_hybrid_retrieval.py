"""混合检索的独立向量参考、持久化、权限与失败边界。"""
from dataclasses import asdict
import sqlite3
import threading

import pytest

from game_agent import HashEmbedder, MemoryRecord, MemoryStore
from game_agent.memory import EventContext, EventQuery, EventScope
from game_agent.memory.hybrid import fuse_rankings


class ToyEmbedder(HashEmbedder):
    """人工定义两类等义词，用于确定性管线验证，不代表真实语义模型。"""
    def __init__(self, dim=2):
        super().__init__(dim)
        self.calls, self.fail = [], False

    def embed(self, texts):
        texts = list(texts)
        self.calls.append(texts)
        if self.fail:
            raise RuntimeError('embedding offline')
        return [([1., 0.] if any(word in text for word in ('feline', '猫咪', 'kitten'))
                 else [0., 1.]) + [0.] * (self.dim - 2) for text in texts]


def complete_index(store, scope):
    while True:
        progress = store.index_archive(scope)
        assert not progress['errors']
        if progress['complete']:
            return


def test_same_evidence_lexical_dense_and_old_low_importance():
    emb = ToyEmbedder()
    store = MemoryStore(emb)
    scope = EventScope(as_of=500, player_id='P')
    try:
        original = store.add(MemoryRecord('feline resting by the river', 1,
                                         importance=1, player_id='P'))
        for i in range(200):
            store.add(MemoryRecord(f'ordinary event {i}', i+2, player_id='P'))
        before = [asdict(r) for r in store.all_valid()]
        complete_index(store, scope)
        dense = store.hybrid_retrieve('猫咪', scope, mode='dense')
        assert dense.hits[0]['source_id'] == store.source_refs(original)[0]['source_id']
        assert dense.hits[0]['content'] == 'feline resting by the river'
        assert dense.diagnostics['dense_complete']
        lexical = store.hybrid_retrieve('feline', scope, mode='bm25')
        hybrid = store.hybrid_retrieve('feline', scope)
        assert lexical.hits[0]['id'] == hybrid.hits[0]['id']
        assert hybrid.hits[0]['ranks'] == {'bm25': 1, 'dense': 1}
        assert [asdict(r) for r in store.all_valid()] == before
    finally:
        store.close()


def test_bm25_and_empty_query_do_not_call_embeddings():
    emb = ToyEmbedder()
    store = MemoryStore(emb)
    try:
        store.archive_input('a kitten', 1)
        emb.fail = True
        result = store.hybrid_retrieve('kitten', EventScope(as_of=2), mode='bm25')
        assert result.hits and not emb.calls
        assert store.hybrid_retrieve(' ', EventScope(as_of=2)).hits == ()
        assert not emb.calls
    finally:
        store.close()


def test_scope_future_instance_and_structured_filters_precede_ranking():
    store = MemoryStore(ToyEmbedder())
    try:
        allowed = store.archive_input('kitten allowed', 2, 'P',
            event=EventContext(event_type='gift', location='port', participants=('P', 'N')))
        store.archive_input('kitten wrong location', 2, 'P', event=EventContext(location='town'))
        store.archive_input('kitten secret', 2, 'Q')
        store.archive_input('kitten shared', 2)
        store.archive_input('kitten future', 20, 'P')
        store.archive_input('kitten occurred future', 2, 'P', event=EventContext(occurred_at=20))
        game = store.archive_input('kitten game secret', 2, 'P',
                                   event=EventContext(instance_id='game'))
        scope = EventScope(as_of=3, player_id='P')
        filters = EventQuery(location='port', participants=('P', 'N'))
        result = store.hybrid_retrieve('kitten', scope, filters=filters, top_k=1, candidate_k=1)
        assert [r['id'] for r in result.hits] == [allowed]
        assert result.hits[0]['ranks']['structured'] == 1
        result = store.hybrid_retrieve('kitten', scope)
        assert {r['content'] for r in result.hits} == {'kitten allowed', 'kitten wrong location'}
        result = store.hybrid_retrieve('kitten', EventScope(as_of=3, player_id='P', include_shared=True))
        assert any(r['content'] == 'kitten shared' for r in result.hits)
        assert store.hybrid_retrieve('kitten', EventScope(
            as_of=3, player_id='P', instance_id='game')).hits[0]['id'] == game
        with pytest.raises(ValueError, match='锚点'):
            store.hybrid_retrieve('kitten', scope, filters=EventQuery(before_event=game))
        with pytest.raises(ValueError, match='锚点'):
            store.hybrid_retrieve('kitten', scope, filters=EventQuery(after_event='missing'))
    finally:
        store.close()


def test_long_source_does_not_fill_route_and_snippet_offsets_are_real():
    store = MemoryStore(ToyEmbedder())
    try:
        text = 'kitten ' * 500
        sid = store.archive_input(text, 1)
        other = store.archive_input('kitten another event', 2)
        result = store.hybrid_retrieve('kitten', EventScope(as_of=3), top_k=2, candidate_k=2)
        assert {r['id'] for r in result.hits} == {sid, other}
        fragment = next(r for r in result.hits if r['id'] == sid)
        assert fragment['content'] == text[fragment['start']:fragment['end']]
        assert fragment['truncated'] and len(fragment['content']) <= 512
        assert result.diagnostics['route_hits'] == {'bm25': 2, 'dense': 2}
    finally:
        store.close()


def test_hint_resolves_to_evidence_without_independent_or_duplicate_votes():
    store = MemoryStore(ToyEmbedder())
    try:
        evidence = store.add(MemoryRecord('她递给我一枚旧徽章', 1, player_id='P'))
        secret = store.add(MemoryRecord('Q 的隐私', 1, player_id='Q'))
        hint = store.add(MemoryRecord('feline trust', 2, player_id='P', type='reflection',
                                      evidence=[evidence, evidence, secret, 99999]))
        scope = EventScope(as_of=3, player_id='P')
        result = store.hybrid_retrieve('猫咪', scope)
        assert len(result.hits) == 1 and result.hits[0]['content'] == '她递给我一枚旧徽章'
        assert result.hits[0]['ranks'] == {'hint': 1}
        assert result.hits[0]['hint_ids'] == [store.source_refs(hint)[0]['source_id']]
        store.invalidate(hint)
        assert store.hybrid_retrieve('猫咪', scope).hits == ()
        store.add(MemoryRecord('feline no evidence', 2, player_id='P', type='identity'))
        assert store.hybrid_retrieve('猫咪', scope).hits == ()
    finally:
        store.close()


def test_persistent_vectors_restart_revision_dimension_and_rebuild(tmp_path):
    path = str(tmp_path / 'N.db')
    scope = EventScope(as_of=3)
    emb = ToyEmbedder()
    store = MemoryStore(emb, path)
    store.archive_input('kitten original', 1)
    complete_index(store, scope)
    store.close()
    emb = ToyEmbedder()
    store = MemoryStore(emb, path)
    try:
        assert store.hybrid_retrieve('猫咪', scope).hits
        assert emb.calls == [['猫咪']]  # 重开只编码查询，不重新编码历史。
        store.rebuild_archive_index()
        assert store.hybrid_retrieve('猫咪', scope).hits
        assert any('kitten original' in batch for batch in emb.calls)
    finally:
        store.close()
    for kwargs in ({'embedding_version': '2'}, {}):
        emb = ToyEmbedder(3 if not kwargs else 2)
        store = MemoryStore(emb, path, **kwargs)
        try:
            assert store.hybrid_retrieve('猫咪', scope).diagnostics['indexed'] == 1
        finally:
            store.close()


def test_partial_index_and_embedding_failure_are_visible_and_retryable():
    emb = ToyEmbedder()
    store = MemoryStore(emb)
    scope = EventScope(as_of=10)
    try:
        for i in range(5):
            store.archive_input(f'kitten {i}', i)
        result = store.hybrid_retrieve('kitten', scope, index_limit=1)
        assert not result.diagnostics['dense_complete'] and result.diagnostics['remaining'] == 4
        original = store.archive_count()
        emb.fail = True
        result = store.hybrid_retrieve('kitten', scope)
        assert result.hits and result.diagnostics['errors']
        assert not result.diagnostics['dense_complete']
        emb.fail = False
        assert store.hybrid_retrieve('kitten', scope).diagnostics['dense_complete']
        assert store.archive_count() == original
        assert len(store.pending_archive()) == original  # 不冒充派生处理完成。
    finally:
        store.close()


@pytest.mark.parametrize('bad', [[], [[float('nan'), 0]], [[1]], [[1, 0], [0, 1]]])
def test_malformed_query_embedding_degrades_without_data_loss(bad, monkeypatch):
    emb = ToyEmbedder()
    store = MemoryStore(emb)
    try:
        store.archive_input('kitten', 1)
        monkeypatch.setattr(emb, 'embed', lambda texts: bad)
        result = store.hybrid_retrieve('kitten', EventScope(as_of=2))
        assert result.hits and result.diagnostics['errors']
        assert store.archive_count() == 1
    finally:
        store.close()


def test_corrupt_vector_is_evicted_and_repaired(tmp_path):
    path = tmp_path / 'N.db'
    scope = EventScope(as_of=3)
    store = MemoryStore(ToyEmbedder(), str(path))
    try:
        store.archive_input('kitten', 1)
        complete_index(store, scope)
        with sqlite3.connect(path.with_suffix('.archive.db')) as db:
            db.execute("UPDATE chunk_vector SET vector=x'00'")
        result = store.hybrid_retrieve('kitten', scope)
        assert result.hits and not result.diagnostics['dense_complete']
        assert store.hybrid_retrieve('kitten', scope).diagnostics['dense_complete']
    finally:
        store.close()


def test_legacy_derived_snapshot_is_only_a_hint_and_invalid_hint_is_ignored(tmp_path):
    from game_agent.memory.repository import MemoryRepository
    path = str(tmp_path / 'legacy.db')
    repository = MemoryRepository(path)
    with repository.insert(MemoryRecord('旧库的真实观察', 1)) as observation:
        pass
    with repository.insert(MemoryRecord('feline insight', 2, type='reflection',
                                        evidence=[observation])) as reflection:
        pass
    with repository.insert(MemoryRecord('feline invalid', 2, type='identity', valid=False)):
        pass
    repository.close()
    store = MemoryStore(ToyEmbedder(), path)
    try:
        result = store.hybrid_retrieve('猫咪', EventScope(as_of=3))
        assert [r['content'] for r in result.hits] == ['旧库的真实观察']
        assert result.hits[0]['kind'] == 'legacy_snapshot'
        store.invalidate(reflection)
        assert store.hybrid_retrieve('猫咪', EventScope(as_of=3)).hits == ()
    finally:
        store.close()


def test_document_embedding_failure_keeps_lexical_route_and_can_resume(monkeypatch):
    emb = ToyEmbedder()
    store = MemoryStore(emb)
    try:
        store.archive_input('feline history', 1)
        encode = emb.embed
        def fail_history(texts):
            if 'feline history' in texts:
                raise RuntimeError('document encoder unavailable')
            return encode(texts)
        monkeypatch.setattr(emb, 'embed', fail_history)
        result = store.hybrid_retrieve('feline query', EventScope(as_of=2))
        assert result.hits and result.diagnostics['remaining'] == 1
        assert result.diagnostics['errors'][0]['stage'] == 'index_embedding'
        monkeypatch.setattr(emb, 'embed', encode)
        assert store.hybrid_retrieve('feline query', EventScope(as_of=2)).diagnostics['dense_complete']
    finally:
        store.close()


def test_neighbors_are_separate_after_ranked_hits_and_remain_scoped():
    store = MemoryStore(ToyEmbedder())
    try:
        before = store.archive_input('之前说只是猜测', 1, 'P', session_id='s')
        match = store.archive_input('kitten', 2, 'P', session_id='s')
        store.archive_input('Q 秘密', 2, 'Q', session_id='s')
        store.archive_input('未来', 20, 'P', session_id='s')
        result = store.hybrid_retrieve('猫咪', EventScope(as_of=3, player_id='P'),
                                       top_k=1, neighbor_radius=2)
        assert [r['id'] for r in result.hits] == [match]
        assert [r['id'] for r in result.neighbors] == [before]
        assert result.neighbors[0]['neighbor_of'] == match
    finally:
        store.close()


def test_rrf_duplicate_votes_and_reranker_contract():
    a = dict(source_id='a', chunk_id=1, sequence=1, start=0, end=1)
    b = dict(source_id='b', chunk_id=2, sequence=2, start=0, end=1)
    fused = fuse_rankings({'x': [a, a, b], 'y': [b]})
    assert fused[0]['source_id'] == 'b'
    assert fused[1]['score'] == pytest.approx(1/61)
    store = MemoryStore(ToyEmbedder())
    try:
        store.archive_input('kitten first', 1)
        store.archive_input('kitten second', 2)
        def reorder(query, views):
            views[0]['content'] = 'cannot replace evidence'
            return [0, 1]
        result = store.hybrid_retrieve('kitten', EventScope(as_of=3), reranker=reorder)
        assert result.hits[0]['content'] == 'kitten first'
        with pytest.raises(ValueError, match='重排'):
            store.hybrid_retrieve('kitten', EventScope(as_of=3), reranker=lambda q, rows: [])
    finally:
        store.close()


def test_hint_callback_does_not_hold_archive_lock():
    store = MemoryStore(ToyEmbedder())
    try:
        sid = store.archive_input('kitten hint', 1, kind='reflection')
        completed = []
        def accept(source_id):
            thread = threading.Thread(target=lambda: completed.append(store.archived(source_id)))
            thread.start()
            thread.join(2)
            assert not thread.is_alive(), '回查提示时不能持有档案锁'
            return True
        rows = store._archive.retrieval.lexical('kitten', EventScope(as_of=2),
                    EventQuery(), 1, derived=True, accept=accept)
        assert rows[0]['source_id'] == sid and completed
    finally:
        store.close()


@pytest.mark.parametrize('options', [
    {'top_k': 0}, {'candidate_k': True}, {'top_k': 33, 'candidate_k': 32},
    {'mode': 'unknown'}, {'index_limit': -1}, {'neighbor_radius': 3},
])
def test_invalid_options(options):
    store = MemoryStore(ToyEmbedder())
    try:
        with pytest.raises(ValueError):
            store.hybrid_retrieve('query', EventScope(as_of=2), **options)
    finally:
        store.close()
