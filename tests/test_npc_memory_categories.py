"""NPC 五类组合、人设与两库恢复；全部使用离线模型。"""
from dataclasses import fields, replace
import json

import pytest

from game_agent import MemoryRecord, NPC
from game_agent.memory import EventContext, EventScope, PersonaProfile
from tests.test_persistence import _StubLLM


def profile(version=1):
    return PersonaProfile('N', {'social': .7}, background='城里的铁匠',
        values=('重视承诺',), boundaries=('不伤害无辜者',), speech_style='简短直接',
        long_term_goals=('守护家人',), version=version)


def test_snapshot_contains_five_categories_and_detached_current_state(monkeypatch):
    npc = NPC('N', {'social': .7}, _StubLLM(), persona_profile=profile())
    try:
        npc.observe('共享经历', 8, importance=5)
        npc.store.add(MemoryRecord('P 的秘密', 8, player_id='P'))
        npc.store.add(MemoryRecord('自我判断', 8, type='identity'))
        npc.store.add(MemoryRecord('当前计划', 8, type='plan'))
        npc.plan_state.replace([(7, 9, '打铁')], interruption='被打断')
        def forbidden(*args, **kwargs):
            raise AssertionError('五类读取不能调用模型或嵌入')
        monkeypatch.setattr(npc.embedder, 'embed', forbidden)
        snapshot = npc.memory_categories()
        assert [f.name for f in fields(snapshot)] == [
            'persona_core', 'current_state', 'semantic', 'episodic', 'raw_archive']
        assert snapshot.persona_core == profile()
        assert snapshot.current_state.current_activity == '打铁'
        assert snapshot.current_state.plan_memories[0].type == 'plan'
        assert snapshot.semantic[0].type == 'identity'
        assert [m.content for m in snapshot.episodic] == ['共享经历']
        assert snapshot.raw_archive
        scoped = npc.memory_categories(EventScope(as_of=8, player_id='P'))
        assert [m.content for m in scoped.episodic] == ['P 的秘密']
        npc.plan_state.blocks[0] = (7, 9, '休息')
        assert snapshot.current_state.plan_blocks == ((7, 9, '打铁'),)
        scoped.episodic[0].content = '改副本'
        assert npc.store.all_valid(player_id='P')[0].content == 'P 的秘密'
        with pytest.raises(ValueError, match='当前时钟'):
            npc.memory_categories(EventScope(as_of=7))
    finally:
        npc.store.close()


def test_persona_updates_require_explicit_new_version_and_preserve_trait_reference(monkeypatch):
    traits = {'social': .7}
    model = _StubLLM()
    npc = NPC('N', traits, model, persona_profile=profile())
    try:
        before = npc.persona_profile
        for invalid in [replace(before, background='不同背景'), replace(before, name='Q', version=2)]:
            with pytest.raises(ValueError):
                npc.set_persona_profile(invalid)
            assert npc.persona_profile == before and traits == {'social': .7}
        updated = replace(before, traits={'social': .2}, values=('珍惜友谊',), version=2)
        npc.set_persona_profile(updated)
        npc.set_persona_profile(updated)  # 相同配置允许幂等调用。
        assert npc.persona_traits is traits and traits == {'social': .2}
        captured = []
        monkeypatch.setattr(model, 'complete', lambda ctx: captured.append(ctx) or '回答')
        npc.speak('P', '你好', 0, remember=False)
        assert "'social': 0.2" in captured[0].system
        assert before.traits['social'] == .7
        traits['social'] = .3  # 旧显式可变接口保持，不宣称是人格锁。
        assert npc.persona_profile.traits['social'] == .3
    finally:
        npc.store.close()


def test_reflection_and_decay_do_not_overwrite_persona_core():
    npc = NPC('N', {'social': .7}, _StubLLM(), persona_profile=profile())
    try:
        npc.observe('P 帮助我', 1, player_id='P', importance=8)
        npc.reflect_relationship('P', 2)
        assert npc.reflect_identity(3)
        npc.forget(1000)
        assert npc.persona_profile == profile()
        assert npc.memory_categories().semantic
    finally:
        npc.store.close()


def test_profile_and_categories_survive_save_load_and_legacy_metadata(tmp_path):
    npc = NPC.create('N', {'social': .7}, _StubLLM(), data_dir=str(tmp_path),
                     persona_profile=profile())
    npc.observe('经历', 8, importance=5)
    npc.set_persona_profile(replace(profile(), background='新背景', version=2))
    expected = npc.persona_profile
    npc.save()
    npc.store.close()
    restored = NPC.load(str(tmp_path / 'N.db'), _StubLLM())
    try:
        assert restored.persona_profile == expected
        assert restored.memory_categories().episodic[0].content == '经历'
        metadata = restored.store.get_meta('npc')
        metadata.pop('persona_profile')
        restored.store.set_meta('npc', metadata)
    finally:
        restored.store.close()
    legacy = NPC.load(str(tmp_path / 'N.db'), _StubLLM())
    try:
        assert legacy.persona_profile == PersonaProfile('N', {'social': .7})
        assert legacy.memory_categories().raw_archive
    finally:
        legacy.store.close()


def test_independent_two_library_checkpoint_and_legacy_state(tmp_path):
    npc = NPC.create('N', {'social': .7}, _StubLLM(), data_dir=str(tmp_path / 'src'),
                     persona_profile=profile())
    npc.observe('检查点经历', 8, importance=5)
    npc.plan_state.replace([(7, 9, '打铁')], interruption='中断')
    state = json.loads(json.dumps(npc.checkpoint_state()))
    path = tmp_path / 'restored.db'
    npc.store.backup(str(path))
    npc.store.backup_archive(str(tmp_path / 'restored.archive.db'))
    npc.store.close()
    restored = NPC.from_checkpoint(str(path), state, _StubLLM())
    try:
        snapshot = restored.memory_categories()
        assert snapshot.persona_core == profile()
        assert snapshot.current_state.interruption == '中断'
        assert snapshot.episodic[0].content == '检查点经历'
    finally:
        restored.store.close()
    state.pop('persona_profile')
    legacy = NPC.from_checkpoint(str(path), state, _StubLLM())
    try:
        assert legacy.persona_profile == PersonaProfile('N', {'social': .7})
    finally:
        legacy.store.close()


def test_existing_create_does_not_silently_replace_profile(tmp_path):
    npc = NPC.create('N', {'social': .7}, _StubLLM(), data_dir=str(tmp_path),
                     persona_profile=profile())
    npc.store.close()
    with pytest.raises(ValueError, match='显式更新'):
        NPC.create('N', {'social': .7}, _StubLLM(), data_dir=str(tmp_path),
                   persona_profile=replace(profile(), version=2))
    restored = NPC.load(str(tmp_path / 'N.db'), _StubLLM())
    try:
        assert restored.persona_profile == profile()
    finally:
        restored.store.close()


def test_instance_snapshot_does_not_include_spatial_plan():
    npc = NPC('N', {'social': .7}, _StubLLM())
    try:
        npc.plan_state.replace([(0, 24, '空间计划')], interruption='空间中断')
        npc.store.archive_input('本局事件', 0, event=EventContext(instance_id='game'))
        snapshot = npc.memory_categories(EventScope(as_of=0, instance_id='game'))
        assert snapshot.current_state.plan_blocks == ()
        assert snapshot.current_state.current_activity == snapshot.current_state.interruption == ''
        assert len(snapshot.raw_archive) == 1
    finally:
        npc.store.close()
