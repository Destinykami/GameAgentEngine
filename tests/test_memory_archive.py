"""无网络验证 NPC 档案隔离、原文保真、补处理和增长边界。"""
import sqlite3

import pytest

from game_agent import HashEmbedder, MemoryRecord, MemoryStore
from game_agent.memory.archive import ArchiveRepository
from game_agent.memory.errors import ArchiveWriteError


def test_raw_history_is_independent_and_survives_derived_merge(tmp_path):
    a = MemoryStore(HashEmbedder(), str(tmp_path / 'A.db'))
    b = MemoryStore(HashEmbedder(), str(tmp_path / 'B.db'))
    try:
        first = a.add(MemoryRecord('玩家随口说：桃音，红矿石挺漂亮', 1, importance=1, player_id='P'))
        a.merge_observation(first, 8, new_content='玩家随口说：桃音，红矿石挺漂亮，还闪着光')
        hit = a.search_archive('红矿石', player_id='P')[0]
        assert hit['content'] == '玩家随口说：桃音，红矿石挺漂亮'
        assert a.read_archive(hit['id'], player_id='P').content == hit['content']
        assert b.search_archive('红矿石', player_id='P') == []
        assert b.read_archive(hit['id'], player_id='P') is None
        assert a.archive_identity != b.archive_identity
        assert a.source_refs(first) == [{'archive_id': a.archive_identity, 'source_id': hit['id']}]
        assert (tmp_path / 'A.archive.db').is_file()
        assert (tmp_path / 'B.archive.db').is_file()
    finally:
        a.close()
        b.close()


def test_raw_failure_and_restart_can_retry_once(tmp_path):
    class Fail(HashEmbedder):
        def embed(self, texts):
            raise RuntimeError('embedding offline')
    path = str(tmp_path / 'A.db')
    store = MemoryStore(Fail(), path)
    with pytest.raises(RuntimeError, match='offline'):
        store.add(MemoryRecord('不可丢失的原句', 3, player_id='P'))
    pending = store.pending_archive()
    assert len(pending) == 1 and pending[0].content == '不可丢失的原句'
    assert pending[0].attempts == 1 and store.count() == 0
    store.close()
    restored = MemoryStore(HashEmbedder(), path)
    try:
        assert len(restored.retry_pending_records()) == 1
        assert restored.retry_pending_records() == []
        assert restored.count() == restored.archive_count() == 1
        assert restored.pending_archive() == []
    finally:
        restored.close()


def test_post_commit_marker_failure_does_not_duplicate_projection(tmp_path, monkeypatch):
    store = MemoryStore(HashEmbedder(), str(tmp_path / 'A.db'))
    original = store.archive_done
    def fail(source_id):
        raise OSError('marker failed')
    monkeypatch.setattr(store, 'archive_done', fail)
    try:
        with pytest.raises(OSError, match='marker'):
            store.add(MemoryRecord('已提交的事件', 1))
        assert store.count() == 1
        monkeypatch.setattr(store, 'archive_done', original)
        assert len(store.retry_pending_records()) == 1
        assert store.count() == store.archive_count() == 1
    finally:
        store.close()


def test_scope_time_exact_read_and_session_neighbors():
    store = MemoryStore(HashEmbedder())
    try:
        s1 = store.archive_input('桃音说这只是个假设', 1, 'P', session_id='s')
        s2 = store.archive_input('红矿石不能买', 2, 'P', session_id='s')
        store.archive_input('其他玩家的红矿石', 2, 'Q', session_id='s')
        store.archive_input('未来的红矿石', 100, 'P', session_id='s')
        store.archive_input('共享的红矿石', 3)
        assert store.read_archive(s2) is None
        assert store.read_archive(s2, player_id='Q') is None
        assert store.search_archive('红矿石', player_id='P', before=3)[0]['id'] == s2
        assert len(store.search_archive('红矿石', player_id='P', include_shared=True, before=3)) == 2
        assert [r.id for r in store.archive_neighbors(s2, player_id='P', before=3)] == [s1, s2]
        assert store.archive_neighbors(s2, player_id='Q') == []
        assert store.search_archive('桃音', player_id='P')[0]['id'] == s1
        assert store.search_archive('" OR * )', player_id='P') == []
    finally:
        store.close()


def test_growth_preserves_low_salience_and_bounded_vector_cache():
    store = MemoryStore(HashEmbedder(), vector_cache_limit=3)
    try:
        store.add(MemoryRecord('很久以前随口提起蓝铜矿石', 0, importance=1, player_id='P'))
        for i in range(80):
            store.add(MemoryRecord(f'第{i}次普通日常', i + 1, importance=2, player_id='P'))
        assert len(store._vec_cache) == 3
        assert store.search_archive('蓝铜矿石', player_id='P', before=100)[0]['timestamp'] == 0
        recent = store.working_memories('P', 100, limit=4)
        assert len(recent) <= 4 and all(m['timestamp'] >= 76 for m in recent)
        store.rebuild_archive_index()
        assert len(store.search_archive('蓝铜矿石', player_id='P')) == 1
    finally:
        store.close()


def test_legacy_rows_are_snapshots_and_missing_or_wrong_archive_fails(tmp_path):
    from game_agent.memory.repository import MemoryRepository
    path = str(tmp_path / 'A.db')
    repository = MemoryRepository(path)
    with repository.insert(MemoryRecord('旧库仅剩的文本', 1)):
        pass
    repository.close()
    store = MemoryStore(HashEmbedder(), path)
    raw = store.search_archive('旧库')[0]
    assert raw['kind'] == 'legacy_snapshot' and store.archive_count() == 1
    store.close()
    archive_path = tmp_path / 'A.archive.db'
    archive_path.rename(tmp_path / 'saved.db')
    with pytest.raises(FileNotFoundError, match='档案丢失'):
        MemoryStore(HashEmbedder(), path)
    other = ArchiveRepository(str(archive_path))
    other.close()
    with pytest.raises(ValueError, match='身份不匹配'):
        MemoryStore(HashEmbedder(), path)


def test_archive_append_failure_leaves_no_main_record(monkeypatch):
    store = MemoryStore(HashEmbedder())
    def fail(*args, **kwargs):
        raise sqlite3.OperationalError('archive unavailable')
    monkeypatch.setattr(store._archive, 'append', fail)
    try:
        with pytest.raises(ArchiveWriteError, match='unavailable'):
            store.add(MemoryRecord('原文不可写', 0))
        assert store.count() == 0
    finally:
        store.close()
