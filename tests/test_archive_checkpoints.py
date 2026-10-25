"""每 NPC 双库检查点、旧代兼容与归档未来隔离。"""
import hashlib
import json
import sqlite3

import pytest

from game_agent import World, Location
from game_agent.world import checkpoints
from tests.test_persistence import _StubLLM


def setup_world(path):
    w = World('W', [Location('L', 0, 0)], path=str(path / 'world.db'))
    for name in ('A', 'B'):
        w.add_npc(name, {}, _StubLLM(), data_dir=str(path))
    return w


def test_two_archives_restore_same_generation_and_pending_work(tmp_path):
    w = setup_world(tmp_path / 'live')
    root = str(tmp_path / 'checkpoint')
    try:
        w.advance(2)
        w.npc('A').observe('很早的蓝铜矿原文', 1, 'P', importance=1)
        source = w.npc('A').store.archive_input('尚未处理的话', 2, 'P',
            metadata={'projection': 'observation', 'content': 'P 对我说: 尚未处理的话',
                      'importance': 3})
        w.npc('B').observe('B 私有的不同经历', 2, 'Q')
        w.save_checkpoint(root)
        directory, manifest = checkpoints.read(root)
        assert manifest['version'] == 2 and len(manifest['files']) == 5
        future_id = w.npc('A').observe('未来的新原文', 100, 'P')
        future_source = w.npc('A').store.source_refs(future_id)[0]['source_id']
        restored = World.from_checkpoint(root, str(tmp_path / 'restored'), _StubLLM())
        try:
            a, b = restored.npc('A'), restored.npc('B')
            assert a.store.archive_identity == w.npc('A').store.archive_identity
            assert a.store.search_archive('蓝铜矿', player_id='P')[0]['content'] == '很早的蓝铜矿原文'
            assert a.store.read_archive(future_source, player_id='P') is None
            assert all(hit['id'] != future_source for hit in
                       a.store.search_archive('未来的新原文', player_id='P'))
            assert b.store.search_archive('蓝铜矿', player_id='P') == []
            assert a.store.pending_archive()[0].id == source
            assert a.retry_pending_memories()['failed'] == []
            assert a.store.read_archive(source, player_id='P').state == 'done'
            assert str(tmp_path / 'restored') in a.store.archive_path
            assert checkpoints.read(root)[1] == manifest
        finally:
            restored.close()
    finally:
        w.close()


def test_missing_archive_and_wrong_pair_are_rejected(tmp_path):
    w = setup_world(tmp_path / 'live')
    try:
        root = str(tmp_path / 'checkpoint')
        w.save_checkpoint(root)
        directory, manifest = checkpoints.read(root)
        first, second = manifest['state']['npcs']
        raw = directory / first['archive_file']
        original = raw.read_bytes()
        raw.unlink()
        with pytest.raises(ValueError, match='校验'):
            World.from_checkpoint(root, str(tmp_path / 'out'), _StubLLM())
        raw.write_bytes((directory / second['archive_file']).read_bytes())
        manifest['files'][first['archive_file']] = hashlib.sha256(raw.read_bytes()).hexdigest()
        (directory / 'manifest.json').write_text(json.dumps(manifest))
        with pytest.raises(ValueError, match='身份不匹配'):
            World.from_checkpoint(root, str(tmp_path / 'out'), _StubLLM())
        assert not (tmp_path / 'out').exists()
    finally:
        w.close()


def test_legacy_version_one_is_imported_as_snapshots_only(tmp_path):
    w = setup_world(tmp_path / 'live')
    try:
        w.npc('A').observe('旧版本剩下的观察', 1)
        root = str(tmp_path / 'checkpoint')
        w.save_checkpoint(root)
        directory, manifest = checkpoints.read(root)
        # 构造真实旧格式：只有主库，且主库不包含新的档案身份和来源表。
        manifest['version'] = 1
        for npc in manifest['state']['npcs']:
            archive = npc.pop('archive_file')
            (directory / archive).unlink()
            del manifest['files'][archive]
            database = directory / npc['file']
            with sqlite3.connect(database) as conn:
                conn.execute("DELETE FROM meta WHERE key LIKE 'archive_%'")
                conn.execute('DROP TABLE memory_source')
            manifest['files'][npc['file']] = hashlib.sha256(database.read_bytes()).hexdigest()
        (directory / 'manifest.json').write_text(json.dumps(manifest))
        restored = World.from_checkpoint(root, str(tmp_path / 'restored'), _StubLLM())
        try:
            hits = restored.npc('A').store.search_archive('旧版本')
            assert len(hits) == 1 and hits[0]['kind'] == 'legacy_snapshot'
            assert restored.npc('B').store.archive_count() == 0
            restored.save_checkpoint(str(tmp_path / 'v2'))
            assert checkpoints.read(str(tmp_path / 'v2'))[1]['version'] == 2
        finally:
            restored.close()
    finally:
        w.close()
