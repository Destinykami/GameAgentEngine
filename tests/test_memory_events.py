"""通用事件查询：证据、组合操作、隔离、稳定分页及档案迁移。"""
from dataclasses import replace
import sqlite3

import pytest

from game_agent import HashEmbedder, MemoryStore
from game_agent.memory import EventContext, EventQuery, EventScope
from game_agent.memory.archive import ArchiveRepository
from game_agent.memory.errors import ArchiveWriteError


@pytest.fixture
def store():
    class NoEmbed(HashEmbedder):
        def embed(self, texts):
            raise AssertionError('事件查询不能调用嵌入')
    value = MemoryStore(NoEmbed())
    yield value
    value.close()


def append(store, text, now, *, player='P', occurred=None, event_type='dialogue',
           speaker='P', **context):
    return store.archive_input(text, now, player, kind='dialogue_in', speaker=speaker,
        event=EventContext(event_type=event_type, occurred_at=occurred, **context))


def test_composed_first_gift_then_last_utterance_and_exact_source(store):
    scope = EventScope(player_id='P', as_of=20)
    first = append(store, '  我会回来。\n', 1, occurred=1, participants=('N',), location='码头')
    gift = append(store, 'P 送出一块红矿石', 2, occurred=2, event_type='gift',
                  actor='P', target='N', location='码头', evidence_kind='observation')
    append(store, '后来闲聊', 3, occurred=3, location='码头')
    found = store.query_events(scope, EventQuery(event_types=('gift',), location='码头',
        participants=('N', 'P'), text='红矿石'), limit=1).events[0]
    assert found.source_id == gift
    previous = store.query_events(scope, EventQuery(event_types=('dialogue',),
        before_event=found.source_id, speaker='P', descending=True), limit=1).events[0]
    assert previous.source_id == first
    assert store.read_event_source(previous.source_id, scope).content == '  我会回来。\n'
    assert store.count_events(scope, EventQuery(location='码头')) == 3
    assert not hasattr(previous, 'content')
    assert len(store.pending_archive()) == 3  # 未处理也可取证


def test_all_filters_and_long_source_count_once(store):
    source = append(store, '红矿石' * 600, 10, occurred=2, actor='P', target='N',
        participants=('旁观者',), location='码头')
    append(store, '红矿石', 11, occurred=3, actor='Q', target='N', location='城门')
    scope = EventScope(player_id='P', as_of=12)
    query = EventQuery(event_types=('dialogue',), evidence_kinds=('utterance',),
        actor='P', target='N', speaker='P', participants=('P', 'N', '旁观者'),
        location='码头', session_id=source, occurred_after=1, occurred_before=2,
        observed_after=10, observed_before=10, text='红矿石')
    assert store.count_events(scope, query) == 1
    assert [r.source_id for r in store.query_events(scope, query).events] == [source]
    assert store.count_events(scope, replace(query, participants=('不存在的人',))) == 0
    assert store.count_events(scope, replace(query, text='" OR * )')) == 0
    assert store.count_events(scope, replace(query, actor="P' OR 1=1 --")) == 0


def test_occurrence_observation_and_append_order_are_distinct(store):
    late = append(store, '后来才听到的旧事', 10, occurred=1)
    early = append(store, '当前看到的事', 5, occurred=5)
    unknown = append(store, '不知发生时间', 6)
    scope = EventScope(player_id='P', as_of=20)
    assert [e.source_id for e in store.query_events(scope).events] == [late, early, unknown]
    assert [e.source_id for e in store.query_events(scope, EventQuery(
        order_by='occurred_at')).events] == [late, early]
    assert [e.source_id for e in store.query_events(scope, EventQuery(
        order_by='observed_at')).events] == [early, unknown, late]
    assert store.count_events(scope, EventQuery(order_by='occurred_at')) == 2
    assert store.count_events(scope, EventQuery(occurred_before=2, observed_after=9)) == 1
    assert store.count_events(EventScope(player_id='P', as_of=6)) == 2
    assert store.read_event_source(late, EventScope(player_id='P', as_of=6)) is None


def test_scope_protects_query_count_source_and_anchors(store):
    p = append(store, 'P 的话', 1)
    q = append(store, 'Q 的话', 1, player='Q', participants=('P',))
    shared = append(store, '公开事件', 1, player=None)
    future = append(store, '未来获知的旧事', 100, occurred=1)
    future_occurrence = append(store, '尚未发生的事件', 1, occurred=100)
    scope = EventScope(player_id='P', as_of=5)
    assert store.count_events(scope) == 1
    assert store.count_events(replace(scope, include_shared=True)) == 2
    assert store.count_events(EventScope(as_of=5)) == 1
    assert store.query_events(scope).events[0].source_id == p
    for invisible in (q, shared, future, future_occurrence, 'absent'):
        assert store.read_event_source(invisible, scope) is None
        with pytest.raises(ValueError, match='锚点不可见或不存在'):
            store.query_events(scope, EventQuery(before_event=invisible))
        with pytest.raises(ValueError, match='锚点不可见或不存在'):
            store.count_events(scope, EventQuery(after_event=invisible))
    assert store.count_events(scope, EventQuery(participants=('Q',))) == 0


@pytest.mark.parametrize('order_by', ['sequence', 'occurred_at', 'observed_at'])
@pytest.mark.parametrize('descending', [False, True])
def test_keyset_pages_freeze_append_watermark_and_break_ties(store, order_by, descending):
    ids = [append(store, f'原句{i}', i // 2 + 1, occurred=i // 2 + 1) for i in range(7)]
    scope = EventScope(player_id='P', as_of=50)
    query = EventQuery(order_by=order_by, descending=descending)
    first = store.query_events(scope, query, limit=2)
    assert first.next_cursor
    inserted = append(store, '回填旧时间', 1, occurred=1)
    rows = list(first.events)
    cursor = first.next_cursor
    while cursor:
        page = store.query_events(scope, query, limit=2, cursor=cursor)
        rows.extend(page.events)
        cursor = page.next_cursor
    assert [r.source_id for r in rows] == (list(reversed(ids)) if descending else ids)
    assert inserted not in {r.source_id for r in rows}
    assert store.count_events(scope, query) == 8


def test_cursor_binding_and_bounds(store):
    for i in range(3):
        append(store, '原句', i)
    scope = EventScope(player_id='P', as_of=10)
    cursor = store.query_events(scope, limit=1).next_cursor
    for other_scope, query in ((replace(scope, player_id='Q'), EventQuery()),
                               (replace(scope, as_of=11), EventQuery()),
                               (scope, EventQuery(descending=True))):
        with pytest.raises(ValueError, match='游标不属于'):
            store.query_events(other_scope, query, cursor=cursor)
    with pytest.raises(ValueError, match='游标不属于'):
        # 档案身份即便被替换，查询范围也不能扩大。
        store.query_events(scope, cursor=replace(cursor, archive_id='another-npc'))
    for limit in (0, -1, 129, True, 1.5):
        with pytest.raises(ValueError):
            store.query_events(scope, limit=limit)


def test_other_npc_cannot_read_ids_or_use_cursors(store):
    source = append(store, '只属于这个 NPC', 1)
    append(store, '第二条', 2)
    scope = EventScope(player_id='P', as_of=10)
    cursor = store.query_events(scope, limit=1).next_cursor
    other = MemoryStore(HashEmbedder())
    try:
        assert other.query_events(scope).events == ()
        assert other.count_events(scope) == 0
        assert other.read_event_source(source, scope) is None
        with pytest.raises(ValueError, match='游标不属于'):
            other.query_events(scope, cursor=cursor)
    finally:
        other.close()


def test_atomic_source_event_pending_and_text_index(store, monkeypatch):
    original = store._archive._index
    def fail(*args):
        original(*args)
        raise RuntimeError('index failed')
    monkeypatch.setattr(store._archive, '_index', fail)
    with pytest.raises(ArchiveWriteError, match='index failed'):
        append(store, '不应部分提交', 1)
    assert store.archive_count() == store.count_events(EventScope(player_id='P', as_of=2)) == 0
    assert store.pending_archive() == []
    assert store.search_archive('部分提交', player_id='P') == []


def test_event_key_is_idempotent_and_rejects_mutated_context(store):
    ctx = EventContext(event_type='help', actor='P', target='N', location='城门')
    first = store.archive_input('尝试帮忙', 1, 'P', event_key='command-1', event=ctx)
    assert store.archive_input('尝试帮忙', 1, 'P', event_key='command-1', event=ctx) == first
    with pytest.raises(ArchiveWriteError, match='上下文不一致'):
        store.archive_input('尝试帮忙', 1, 'P', event_key='command-1', event=replace(ctx, location='码头'))
    assert store.archive_count() == 1


def test_upgrade_old_archive_preserves_unknowns_and_does_not_rescan(tmp_path, monkeypatch):
    path = str(tmp_path / 'old.archive.db')
    archive = ArchiveRepository(path)
    sid = archive.append('旧发言', 2, 'P', kind='dialogue_in', speaker='P')
    archive.close()
    with sqlite3.connect(path) as conn:
        conn.executescript("DROP TABLE event; DROP TABLE event_participant; "
                           "DELETE FROM archive_meta WHERE key='event_index_v1';")
    archive = ArchiveRepository(path)
    scope = EventScope(player_id='P', as_of=5)
    event = archive.query_events(scope, EventQuery()).events[0]
    assert event.source_id == sid and event.participants == ('P',)
    assert event.occurred_at is event.observed_at is event.location is None
    assert archive.query_events(scope, EventQuery(order_by='observed_at')).events == ()
    assert archive.read_event_source(sid, scope).content == '旧发言'
    archive.close()
    statements = []
    original_connect = sqlite3.connect
    def connect(*args, **kwargs):
        conn = original_connect(*args, **kwargs)
        conn.set_trace_callback(statements.append)
        return conn
    monkeypatch.setattr(sqlite3, 'connect', connect)
    archive = ArchiveRepository(path)
    assert archive.count_events(scope, EventQuery()) == 1
    assert not any('INSERT OR IGNORE INTO event\n' in s for s in statements)
    archive.close()


def test_backup_restore_and_cursor_survive_reopen(tmp_path):
    path = str(tmp_path / 'N.db')
    store = MemoryStore(HashEmbedder(), path)
    for i in range(3):
        append(store, str(i), i, actor='P', target='N', location='桥边')
    scope = EventScope(player_id='P', as_of=10)
    cursor = store.query_events(scope, limit=1).next_cursor
    backup = str(tmp_path / 'backup.archive.db')
    store.backup_archive(backup)
    store.close()
    archive = ArchiveRepository(backup)
    try:
        page = archive.query_events(scope, EventQuery(), cursor=cursor)
        assert len(page.events) == 2
        assert all(e.location == '桥边' and e.participants == ('N', 'P') for e in page.events)
    finally:
        archive.close()


@pytest.mark.parametrize('construct', [
    lambda: EventScope(as_of=float('inf')),
    lambda: EventScope(as_of=None),
    lambda: EventQuery(order_by='sequence; DROP TABLE source'),
    lambda: EventQuery(occurred_after=3, occurred_before=1),
    lambda: EventQuery(observed_before=float('nan')),
    lambda: EventQuery(evidence_kinds=('fact',)),
    lambda: EventContext(occurred_at=float('inf')),
])
def test_invalid_contracts_are_rejected(construct):
    with pytest.raises(ValueError):
        construct()
