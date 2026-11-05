"""五类组织的兼容、权限、有界读取与只读契约。"""
from dataclasses import FrozenInstanceError, asdict
import json

import pytest

from game_agent import HashEmbedder, MemoryRecord, MemoryStore
from game_agent.memory import EventContext, EventScope, MemoryCategory, PersonaProfile


@pytest.mark.parametrize('kind,category', [
    ('plan', MemoryCategory.CURRENT_STATE),
    ('reflection', MemoryCategory.SEMANTIC), ('identity', MemoryCategory.SEMANTIC),
    ('observation', MemoryCategory.EPISODIC), ('episode', MemoryCategory.EPISODIC),
    ('custom', None),
])
def test_record_category_preserves_serialized_contract(kind, category):
    rec = MemoryRecord('内容', 1, type=kind)
    assert rec.category == category
    assert 'category' not in asdict(rec)
    assert MemoryRecord(**asdict(rec)) == rec


def test_persona_profile_is_detached_immutable_and_json_serializable():
    traits, values = {'social': .7}, ['重视承诺']
    profile = PersonaProfile('N', traits, values=values, boundaries=['不伤害无辜者'])
    traits['social'] = .1
    values.append('其他')
    assert profile.traits['social'] == .7 and profile.values == ('重视承诺',)
    with pytest.raises(TypeError):
        profile.traits['social'] = 0
    with pytest.raises(FrozenInstanceError):
        profile.background = '覆写'
    payload = profile.to_dict()
    restored = PersonaProfile.from_dict(json.loads(json.dumps(payload)))
    payload['traits']['social'] = 0
    assert restored == profile


@pytest.mark.parametrize('kwargs', [
    {'version': True}, {'version': 0}, {'traits': {'x': float('nan')}},
    {'values': '不能作为字符串'}, {'boundaries': ['']},
])
def test_invalid_persona_is_rejected(kwargs):
    with pytest.raises(ValueError):
        PersonaProfile('N', **kwargs)


def test_organization_is_scoped_ordered_bounded_and_read_only(monkeypatch):
    emb = HashEmbedder()
    store = MemoryStore(emb)
    try:
        ids = {}
        for kind in ('plan', 'reflection', 'identity', 'observation', 'episode'):
            for index in range(4):
                ids[kind, index] = store.add(MemoryRecord(
                    f'{kind}:{index}', index, type=kind, player_id='P', last_accessed=0))
        store.add(MemoryRecord('另一关系', 3, type='reflection', player_id='Q'))
        shared = store.add(MemoryRecord('共享观察', 2.5))
        invalid = store.add(MemoryRecord('失效判断', 3, type='identity', player_id='P'))
        store.invalidate(invalid)
        store.add(MemoryRecord('未来', 50, type='identity', player_id='P'))
        before = [asdict(rec) for rec in store.all_valid()]
        raw_count = store.archive_count()
        def forbidden(*args, **kwargs):
            raise AssertionError('分类读取不得编码或全量读取派生记录')
        monkeypatch.setattr(emb, 'embed', forbidden)
        monkeypatch.setattr(store, 'all_valid', forbidden)
        result = store.organize(EventScope(as_of=4, player_id='P'), limit=2)
        assert [r.id for r in result.current_state] == [ids['plan', 3], ids['plan', 2]]
        assert [r.id for r in result.semantic] == [ids['identity', 3], ids['reflection', 3]]
        assert [r.id for r in result.episodic] == [ids['episode', 3], ids['observation', 3]]
        assert len(result.raw_archive) == 2
        assert all(r.player_id == 'P' for r in result.raw_archive)
        assert store.organize(EventScope(as_of=4)).episodic[0].id == shared
        both = store.organize(EventScope(as_of=4, player_id='P', include_shared=True))
        assert any(r.id == shared for r in both.episodic)
        assert all(r.timestamp <= 4 for r in both.semantic)
        assert all(r.id != invalid for r in both.semantic)
        assert all(r.player_id in ('P', None) for r in both.semantic)
        result.semantic[0].content = '修改副本'
        result.semantic[0].evidence.append(999)
        assert [asdict(rec) for rec in store._repository.all_valid()] == before
        assert store.archive_count() == raw_count
    finally:
        store.close()


def test_instance_scope_does_not_borrow_global_derived_records():
    store = MemoryStore(HashEmbedder())
    try:
        store.add(MemoryRecord('全局观察', 1))
        store.add(MemoryRecord('全局判断', 1, type='identity'))
        for instance in ('a', 'b'):
            store.archive_input(instance, 2, event=EventContext(instance_id=instance))
        scope = EventScope(as_of=3, instance_id='a')
        result = store.organize(scope)
        assert result.current_state == result.semantic == result.episodic == ()
        assert len(result.raw_archive) == 1
        assert store.read_event_source(result.raw_archive[0].source_id, scope).content == 'a'
    finally:
        store.close()


@pytest.mark.parametrize('limit', [True, 0, -1, 129, 1.5])
def test_invalid_category_limits_are_rejected(limit):
    store = MemoryStore(HashEmbedder())
    try:
        with pytest.raises(ValueError):
            store.organize(EventScope(as_of=1), limit=limit)
    finally:
        store.close()


def test_existing_two_libraries_reopen_without_reclassification_writes(tmp_path):
    path = str(tmp_path / 'N.db')
    store = MemoryStore(HashEmbedder(), path)
    store.add(MemoryRecord('旧身份信念', 1, type='identity'))
    store.add(MemoryRecord('旧情节', 2, type='episode'))
    store.close()
    store = MemoryStore(HashEmbedder(), path)
    try:
        result = store.organize(EventScope(as_of=3))
        assert result.semantic[0].type == 'identity'
        assert result.episodic[0].type == 'episode'
        assert store.count() == store.archive_count() == 2
        assert len(list(tmp_path.glob('*.db'))) == 2
    finally:
        store.close()
