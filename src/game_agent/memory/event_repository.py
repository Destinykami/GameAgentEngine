"""档案内事件索引与受限查询执行；原文不在此复制。"""
from __future__ import annotations

from dataclasses import asdict
import hashlib
import json

from .events import EventContext, EventCursor, EventPage, EventQuery, EventRecord, EventScope


class EventIndex:
    def __init__(self, connection, lock, archive_id: str, tokenize) -> None:
        self._conn, self._lock = connection, lock
        self._archive_id, self._tokenize = archive_id, tokenize
        self._conn.executescript('''
            CREATE INDEX IF NOT EXISTS source_stream_sequence ON source(player_id, sequence);
            CREATE TABLE IF NOT EXISTS event (
                source_id TEXT PRIMARY KEY, event_type TEXT NOT NULL,
                occurred_at REAL, observed_at REAL, actor TEXT, target TEXT,
                location TEXT, evidence_kind TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS event_type_time ON event(event_type, occurred_at, source_id);
            CREATE INDEX IF NOT EXISTS event_occurred ON event(occurred_at, source_id);
            CREATE INDEX IF NOT EXISTS event_observed ON event(observed_at, source_id);
            CREATE INDEX IF NOT EXISTS event_location ON event(location, source_id);
            CREATE TABLE IF NOT EXISTS event_participant (
                source_id TEXT NOT NULL, participant TEXT NOT NULL,
                PRIMARY KEY(source_id, participant));
            CREATE INDEX IF NOT EXISTS participant_events
                ON event_participant(participant, source_id);
        ''')
        if 'instance_id' not in {row[1] for row in self._conn.execute('PRAGMA table_info(event)')}:
            with self._conn:
                self._conn.execute('ALTER TABLE event ADD COLUMN instance_id TEXT')
        self._conn.execute('CREATE INDEX IF NOT EXISTS event_instance '
                           'ON event(instance_id, source_id)')
        # 一次性升级，不解析全部原文，不在每次打开时扫描历史。
        with self._conn:
            if not self._conn.execute(
                    "SELECT 1 FROM archive_meta WHERE key='event_index_v1'").fetchone():
                self._conn.execute('''INSERT OR IGNORE INTO event
                    (source_id,event_type,occurred_at,observed_at,actor,target,location,evidence_kind)
                    SELECT id,kind,NULL,NULL,speaker,NULL,NULL,
                        CASE WHEN kind='legacy_snapshot' THEN 'legacy_snapshot'
                             WHEN hearsay=1 THEN 'report'
                             WHEN kind IN ('dialogue_in','dialogue_out') THEN 'utterance'
                             ELSE 'unclassified' END FROM source''')
                self._conn.execute('''INSERT OR IGNORE INTO event_participant
                    SELECT id,speaker FROM source WHERE speaker IS NOT NULL AND speaker!='' ''')
                self._conn.execute("INSERT INTO archive_meta VALUES ('event_index_v1','complete')")

    @staticmethod
    def context(kind: str, speaker: str | None, hearsay: bool,
                context: EventContext | None) -> EventContext:
        ctx = context or EventContext()
        evidence = ctx.evidence_kind or (
            'legacy_snapshot' if kind == 'legacy_snapshot' else
            'report' if hearsay else
            'utterance' if kind in ('dialogue_in', 'dialogue_out') else
            'action_attempt' if kind == 'action' else
            'derived' if kind in ('reflection', 'episode', 'identity', 'plan') else
            'observation' if kind == 'observation' else 'unclassified')
        participants = tuple(dict.fromkeys(
            (*ctx.participants, *(p for p in (ctx.actor, ctx.target, speaker) if p))))
        return EventContext(ctx.event_type or kind, ctx.occurred_at, ctx.actor, ctx.target,
                            participants, ctx.location, evidence, ctx.instance_id)

    def insert(self, source_id: str, ctx: EventContext, observed_at: float | None) -> None:
        self._conn.execute('INSERT INTO event VALUES (?,?,?,?,?,?,?,?,?)',
            (source_id, ctx.event_type, ctx.occurred_at, observed_at, ctx.actor,
             ctx.target, ctx.location, ctx.evidence_kind, ctx.instance_id))
        self._conn.executemany('INSERT INTO event_participant VALUES (?,?)',
                               ((source_id, p) for p in ctx.participants))

    @staticmethod
    def _scope(scope: EventScope) -> tuple[list[str], list]:
        where = ['s.timestamp<=?', '(e.occurred_at IS NULL OR e.occurred_at<=?)',
                 '(e.observed_at IS NULL OR e.observed_at<=?)']
        args = [scope.as_of, scope.as_of, scope.as_of]
        if scope.instance_id is not None:
            where.append('e.instance_id=?')
            args.append(scope.instance_id)
        if scope.player_id is None:
            where.append('s.player_id IS NULL')
        elif scope.include_shared:
            where.append('(s.player_id=? OR s.player_id IS NULL)')
            args.append(scope.player_id)
        else:
            where.append('s.player_id=?')
            args.append(scope.player_id)
        return where, args

    _FROM = ' FROM source s JOIN event e ON e.source_id=s.id '

    def visible(self, source_id: str, scope: EventScope):
        where, args = self._scope(scope)
        return self._conn.execute('SELECT s.sequence' + self._FROM +
            'WHERE s.id=? AND ' + ' AND '.join(where), [source_id, *args]).fetchone()

    def _filters(self, scope: EventScope, query: EventQuery):
        where, args = self._scope(scope)
        if query.order_by != 'sequence':
            where.append('e.' + query.order_by + ' IS NOT NULL')
        for column, values in (('e.event_type', query.event_types),
                               ('e.evidence_kind', query.evidence_kinds)):
            if values:
                where.append(column + ' IN (' + ','.join('?' for _ in values) + ')')
                args.extend(values)
        for field, column in (('actor', 'e.actor'), ('target', 'e.target'),
                              ('speaker', 's.speaker'), ('location', 'e.location'),
                              ('session_id', 's.session_id')):
            value = getattr(query, field)
            if value is not None:
                where.append(column + '=?')
                args.append(value)
        for participant in query.participants:
            where.append('EXISTS (SELECT 1 FROM event_participant ep '
                         'WHERE ep.source_id=s.id AND ep.participant=?)')
            args.append(participant)
        for prefix, column in (('occurred', 'e.occurred_at'), ('observed', 'e.observed_at')):
            for suffix, op in (('after', '>='), ('before', '<=')):
                value = getattr(query, prefix + '_' + suffix)
                if value is not None:
                    where.append(column + op + '?')
                    args.append(value)
        for field, op in (('after_event', '>'), ('before_event', '<')):
            source_id = getattr(query, field)
            if source_id is not None:
                anchor = self.visible(source_id, scope)
                if anchor is None:
                    raise ValueError('锚点不可见或不存在')
                where.append('s.sequence' + op + '?')
                args.append(anchor['sequence'])
        if query.text.strip():
            terms = self._tokenize(query.text)
            strong = [t for t in terms if len(t) > 1]
            terms = (strong or terms)[:48]
            if not terms:
                where.append('0')
            else:
                match = ' OR '.join('"' + t.replace('"', '""') + '"' for t in terms)
                where.append('s.id IN (SELECT c.source_id FROM source_fts '
                             'JOIN chunk c ON c.id=source_fts.rowid WHERE source_fts MATCH ?)')
                args.append(match)
        return where, args

    def count(self, scope: EventScope, query: EventQuery) -> int:
        with self._lock:
            where, args = self._filters(scope, query)
            return self._conn.execute('SELECT COUNT(*)' + self._FROM +
                'WHERE ' + ' AND '.join(where), args).fetchone()[0]

    def query(self, scope: EventScope, query: EventQuery, *, limit: int = 32,
              cursor: EventCursor | None = None) -> EventPage:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 128:
            raise ValueError('每页事件数须在 1 到 128 之间')
        fingerprint = hashlib.sha256(json.dumps(
            [asdict(scope), asdict(query)], sort_keys=True, ensure_ascii=False,
            allow_nan=False).encode()).hexdigest()
        if cursor and (cursor.archive_id != self._archive_id or cursor.fingerprint != fingerprint):
            raise ValueError('游标不属于当前档案、范围或查询')
        column = {'sequence': 's.sequence', 'occurred_at': 'e.occurred_at',
                  'observed_at': 'e.observed_at'}[query.order_by]
        direction, op = ('DESC', '<') if query.descending else ('ASC', '>')
        with self._lock:
            where, args = self._filters(scope, query)
            high_water = cursor.high_water if cursor else self._conn.execute(
                'SELECT COALESCE(MAX(sequence),0) FROM source').fetchone()[0]
            where.extend(['s.sequence<=?', column + ' IS NOT NULL'])
            args.append(high_water)
            if cursor:
                where.append(f'({column},s.sequence){op}(?,?)')
                args.extend([cursor.sort_value, cursor.sequence])
            rows = self._conn.execute('SELECT s.id,s.sequence,s.kind,s.speaker,s.player_id,'
                's.session_id,s.hearsay,s.hop,e.*,' + column + ' AS sort_value' + self._FROM +
                'WHERE ' + ' AND '.join(where) + f' ORDER BY {column} {direction},'
                f's.sequence {direction} LIMIT ?', [*args, limit + 1]).fetchall()
            page_rows = rows[:limit]
            participants: dict[str, list[str]] = {}
            if page_rows:
                ids = [r['id'] for r in page_rows]
                for row in self._conn.execute('SELECT source_id,participant FROM event_participant '
                        'WHERE source_id IN (' + ','.join('?' for _ in ids) + ') ORDER BY participant', ids):
                    participants.setdefault(row['source_id'], []).append(row['participant'])
            events = tuple(EventRecord(
                r['id'], r['sequence'], r['event_type'], r['occurred_at'], r['observed_at'],
                r['actor'], r['target'], tuple(participants.get(r['id'], [])), r['location'],
                r['evidence_kind'], r['kind'], r['speaker'], r['player_id'], r['session_id'],
                bool(r['hearsay']), r['hop'], r['instance_id']) for r in page_rows)
            next_cursor = None
            if len(rows) > limit:
                last = page_rows[-1]
                next_cursor = EventCursor(self._archive_id, fingerprint, high_water,
                                          last['sort_value'], last['sequence'])
            return EventPage(events, next_cursor)
