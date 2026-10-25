"""离线检查点发布、恢复及故障注入。"""
import json
from pathlib import Path

import pytest

from game_agent import World, Location, HashEmbedder
from game_agent.world import checkpoints
from game_agent.memory.store import MemoryStore
from tests.test_persistence import _StubLLM


def make_world(directory):
    w = World('检查点', [Location('L', 0, 0)], path=str(directory / 'world.db'),
              social_perception=True, rumor_spread=True, consolidation=True,
              player_perception_transition=True, decision_tier_gate=True)
    for name in ['A', 'B']:
        w.add_npc(name, {'social': 0.7}, _StubLLM(), data_dir=str(directory), autonomous=True)
    w.add_agent_player('P', 'L', '目标', _StubLLM())
    return w


def test_checkpoint_restores_full_progress_without_touching_snapshot(tmp_path):
    w = make_world(tmp_path / 'live')
    root = tmp_path / 'checkpoints'
    try:
        npc = w.npc('A')
        npc.observe('共同经历', 8, importance=9)
        npc.set_tier('compressed')
        npc.plan_state.replace([(8, 10, '活动')], interruption='中断')
        w.advance(8)
        # Populate perception watermarks and pending social through public paths.
        w.perceive('A', 8)
        w.add_chain_rule('help', 3, '互助')
        first_state = npc.checkpoint_state()
        generation = w.save_checkpoint(str(root))
        source, manifest = checkpoints.read(str(root))
        assert generation == manifest['generation']
        npc.observe('新的不同经历', 12)
        w.advance(12)
        restored = World.from_checkpoint(str(root), str(tmp_path / 'restored'), _StubLLM(), HashEmbedder())
        try:
            assert restored.clock == 8
            assert restored.npc('A').checkpoint_state() == first_state
            assert len(restored.npc('A').store.all_valid(shared=True)) == 1
            assert restored.agent_model('P') is not None
            assert restored.npc_names() == ('A', 'B')
            # A second checkpoint includes exactly the restored settings, watermarks and queues.
            restored.save_checkpoint(str(tmp_path / 'second'))
            _, second = checkpoints.read(str(tmp_path / 'second'))
            assert second['state'] == manifest['state']
            restored.npc('A').observe('恢复后独立写入', 10)
            assert checkpoints.read(str(root))[1] == manifest
            restored.advance(9)
            restored.save()
        finally:
            restored.close()
        # Legacy loading after checkpoint restoration uses the copied NPC directories.
        legacy = World('检查点', [Location('L', 0, 0)], path=str(tmp_path / 'restored/world.db'))
        try:
            legacy.load(llm=_StubLLM())
            assert legacy.clock == 9 and legacy.npc('A').memory_count() > 0
        finally:
            legacy.close()
    finally:
        w.close()


@pytest.mark.parametrize('stage', ['npc', 'archive', 'world', 'manifest', 'pointer'])
def test_failed_publication_preserves_previous_generation(tmp_path, monkeypatch, stage):
    from game_agent.world.persistence import WorldStore
    w = make_world(tmp_path / 'live')
    root = tmp_path / 'checkpoints'
    try:
        w.advance(1)
        previous = w.save_checkpoint(str(root))
        def fail(*args, **kwargs):
            raise OSError('injected checkpoint failure')
        if stage == 'npc':
            monkeypatch.setattr(MemoryStore, 'backup', fail)
        elif stage == 'archive':
            monkeypatch.setattr(MemoryStore, 'backup_archive', fail)
        elif stage == 'world':
            monkeypatch.setattr(WorldStore, 'backup', fail)
        else:
            original = checkpoints._write_json
            def write(path, value):
                if (stage == 'manifest' and path.name == 'manifest.json') or (
                        stage == 'pointer' and path.name.startswith('.LATEST-')):
                    fail()
                original(path, value)
            monkeypatch.setattr(checkpoints, '_write_json', write)
        w.advance(12)
        with pytest.raises(OSError, match='injected'):
            w.save_checkpoint(str(root))
        directory, manifest = checkpoints.read(str(root))
        assert directory.name == manifest['generation'] == previous
        restored = World.from_checkpoint(str(root), str(tmp_path / 'restored'), _StubLLM())
        try:
            assert restored.clock == 1
        finally:
            restored.close()
        assert not list(root.glob('.pending-*'))
    finally:
        w.close()


def test_corrupt_missing_and_unknown_version_are_rejected(tmp_path):
    w = make_world(tmp_path / 'live')
    try:
        root = tmp_path / 'checkpoints'
        w.save_checkpoint(str(root))
        directory, manifest = checkpoints.read(str(root))
        db = directory / 'world.db'
        original = db.read_bytes()
        db.write_bytes(b'bad')
        with pytest.raises(ValueError, match='校验'):
            World.from_checkpoint(str(root), str(tmp_path / 'out'), _StubLLM())
        assert not (tmp_path / 'out').exists()
        db.write_bytes(original)
        path = directory / 'manifest.json'
        manifest['version'] = 999
        path.write_text(json.dumps(manifest))
        with pytest.raises(ValueError, match='版本'):
            checkpoints.read(str(root))
    finally:
        w.close()


def test_restore_requires_new_directory_and_explicit_callback_bindings(tmp_path):
    w = make_world(tmp_path / 'live')
    root = tmp_path / 'checkpoints'
    effect = lambda *args: None
    try:
        w.add_action_effect('help', effect)
        w.threat_filter = lambda actor, other: False
        w.save_checkpoint(str(root))
        with pytest.raises(ValueError, match='configure'):
            World.from_checkpoint(str(root), str(tmp_path / 'out'), _StubLLM())
        def configure(world):
            world.add_action_effect('help', effect)
            world.threat_filter = lambda actor, other: False
        with pytest.raises(FileExistsError):
            World.from_checkpoint(str(root), str(tmp_path / 'live'), _StubLLM(), configure=configure)
        restored = World.from_checkpoint(str(root), str(tmp_path / 'out'), _StubLLM(), configure=configure)
        restored.close()
    finally:
        w.close()


def test_checkpoint_in_new_process_can_continue_after_source_is_removed(tmp_path):
    import os
    import shutil
    import subprocess
    import sys
    w = make_world(tmp_path / 'live')
    w.advance(8)
    w.npc('A').observe('起始记忆', 8)
    root = str(tmp_path / 'checkpoints')
    w.save_checkpoint(root)
    w.close()
    shutil.rmtree(tmp_path / 'live')
    code = '''
import sys
from game_agent import World, HashEmbedder
from tests.test_persistence import _StubLLM
w = World.from_checkpoint(sys.argv[1], sys.argv[2], _StubLLM(), HashEmbedder())
try:
    assert w.clock == 8 and w.npc('A').memory_count() == 1
    w.step_autonomous(9)
    w.save_checkpoint(sys.argv[3])
finally:
    w.close()
'''
    result = subprocess.run([sys.executable, '-c', code, root,
                             str(tmp_path / 'restored'), str(tmp_path / 'second')],
                            env=dict(os.environ), capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert checkpoints.read(str(tmp_path / 'second'))[1]['state']['name'] == '检查点'


def test_component_watermarks_chain_counts_and_npc_configuration_roundtrip(tmp_path):
    from game_agent.world.extensions import WorldExtensions
    from game_agent.world.perception import PresenceTracker
    from game_agent import NPC
    ext = WorldExtensions()
    ext.add_chain_rule('help', 3, '事件')
    assert ext.record_action('A', 'help', 'B') is None
    other = WorldExtensions()
    other.restore_checkpoint(json.loads(json.dumps(ext.checkpoint_state())))
    assert other.record_action('A', 'help', 'B') is None
    assert other.record_action('A', 'help', 'B') == '事件'
    tracker = PresenceTracker()
    state = {'players': {'A': {'P': ['L', 'full']}}, 'social': {'A': ['B']}}
    tracker.restore_checkpoint(state)
    assert tracker.checkpoint_state() == state
    npc = NPC('A', {}, _StubLLM(), conflict_policy='none', use_relationship=False,
              evidence_types=('observation', 'episode'), evidence_min_relevance=0.3,
              reflection_threshold=5)
    npc.observe('共享', 2, importance=4)
    npc.plan_state.interruption = '中断'
    try:
        state = json.loads(json.dumps(npc.checkpoint_state()))
        path = str(tmp_path / 'A.db')
        npc.store.backup(path)
        npc.store.backup_archive(str(tmp_path / 'A.archive.db'))
        restored = NPC.from_checkpoint(path, state, _StubLLM())
        try:
            assert restored.checkpoint_state() == state
            assert restored.runtime_state().importance_accum == 4
            assert restored.decider.use_relationship is False
        finally:
            restored.store.close()
    finally:
        npc.store.close()


def test_incomplete_callback_rebinding_does_not_leave_a_run_directory(tmp_path):
    w = make_world(tmp_path / 'live')
    try:
        w.add_action_effect('help', lambda *args: None)
        w.save_checkpoint(str(tmp_path / 'checkpoints'))
        with pytest.raises(ValueError, match='重绑定'):
            World.from_checkpoint(str(tmp_path / 'checkpoints'), str(tmp_path / 'out'),
                                  _StubLLM(), configure=lambda world: None)
        assert not (tmp_path / 'out').exists()
    finally:
        w.close()
