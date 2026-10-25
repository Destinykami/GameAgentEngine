"""每 NPC 独立的追加原文、持久全文索引和派生处理队列。"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import re
import sqlite3
import threading
from typing import Any
import uuid

from .event_repository import EventIndex
from .events import EventContext, EventCursor, EventPage, EventQuery, EventScope, _finite


def search_terms(text: str) -> list[str]:
    """预分词兼容中文短名；FTS 不直接解释用户的查询语法。"""
    terms = re.findall(r"[a-z0-9_]+", text.lower())
    for run in re.findall(r"[\u3400-\u9fff]+", text):
        terms.extend(run)
        terms.extend(run[i:i + 2] for i in range(len(run) - 1))
    return list(dict.fromkeys(terms))


@dataclass(frozen=True)
class ArchiveRecord:
    id: str
    sequence: int
    content: str
    timestamp: float
    player_id: str | None
    kind: str
    speaker: str | None
    session_id: str
    hearsay: bool
    hop: int
    metadata: dict[str, Any] = field(default_factory=dict)
    state: str = "pending"
    attempts: int = 0
    error: str = ""


class ArchiveRepository:
    CHUNK_SIZE = 512
    CHUNK_OVERLAP = 64

    def __init__(self, path: str) -> None:
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        try:
            with self._conn:
                self._conn.executescript('''
                    CREATE TABLE IF NOT EXISTS archive_meta (
                        key TEXT PRIMARY KEY, value TEXT NOT NULL);
                    CREATE TABLE IF NOT EXISTS source (
                        sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                        id TEXT UNIQUE NOT NULL, event_key TEXT UNIQUE,
                        content TEXT NOT NULL, timestamp REAL NOT NULL,
                        player_id TEXT, kind TEXT NOT NULL, speaker TEXT,
                        session_id TEXT NOT NULL, hearsay INTEGER NOT NULL,
                        hop INTEGER NOT NULL, metadata TEXT NOT NULL,
                        checksum TEXT NOT NULL);
                    CREATE INDEX IF NOT EXISTS source_stream_time
                        ON source(player_id, timestamp, sequence);
                    CREATE TABLE IF NOT EXISTS processing (
                        source_id TEXT PRIMARY KEY, state TEXT NOT NULL,
                        attempts INTEGER NOT NULL DEFAULT 0, error TEXT NOT NULL DEFAULT '');
                    CREATE INDEX IF NOT EXISTS processing_state ON processing(state);
                    CREATE TABLE IF NOT EXISTS chunk (
                        id INTEGER PRIMARY KEY, source_id TEXT NOT NULL,
                        start INTEGER NOT NULL, end INTEGER NOT NULL, terms TEXT NOT NULL);
                    CREATE INDEX IF NOT EXISTS chunk_source ON chunk(source_id);
                    CREATE VIRTUAL TABLE IF NOT EXISTS source_fts USING fts5(
                        terms, content='chunk', content_rowid='id');
                ''')
                row = self._conn.execute(
                    "SELECT value FROM archive_meta WHERE key='identity'").fetchone()
                self.identity = row[0] if row else uuid.uuid4().hex
                if row is None:
                    self._conn.execute("INSERT INTO archive_meta VALUES ('identity', ?)",
                                       (self.identity,))
            self.events = EventIndex(self._conn, self._lock, self.identity, search_terms)
        except Exception:
            self._conn.close()
            raise

    def append(self, content: str, timestamp: float, player_id: str | None, *,
               kind: str = "observation", speaker: str | None = None,
               session_id: str = "", hearsay: bool = False, hop: int = 0,
               metadata: dict | None = None, event_key: str | None = None,
               event: EventContext | None = None) -> str:
        """原文、片段索引和 pending 在同一事务提交，模型不可参与。"""
        payload = json.dumps(metadata or {}, ensure_ascii=False, allow_nan=False)
        _finite('timestamp', timestamp)
        context = self.events.context(kind, speaker, hearsay, event)
        observed_at = None if kind == 'legacy_snapshot' else timestamp
        with self._lock, self._conn:
            if event_key is not None:
                existing = self._conn.execute(
                    "SELECT id, content, timestamp, player_id, kind, speaker, hearsay, hop "
                    "FROM source WHERE event_key=?", (event_key,)).fetchone()
                if existing:
                    if tuple(existing)[1:] != (content, timestamp, player_id, kind,
                                              speaker, int(hearsay), hop):
                        raise ValueError("同一事件 ID 的原文或来源不一致")
                    old = self._conn.execute('SELECT * FROM event WHERE source_id=?',
                                             (existing[0],)).fetchone()
                    participants = tuple(r[0] for r in self._conn.execute(
                        'SELECT participant FROM event_participant WHERE source_id=? '
                        'ORDER BY participant', (existing[0],)))
                    original = self._conn.execute(
                        'SELECT session_id,metadata FROM source WHERE id=?', (existing[0],)).fetchone()
                    if (tuple(old)[1:] != (context.event_type, context.occurred_at, observed_at,
                            context.actor, context.target, context.location, context.evidence_kind,
                            context.instance_id)
                            or participants != tuple(sorted(context.participants))
                            or (session_id and original['session_id'] != session_id)
                            or json.loads(original['metadata']) != json.loads(payload)):
                        raise ValueError('同一事件 ID 的上下文不一致')
                    return existing[0]
            source_id = uuid.uuid4().hex
            self._conn.execute(
                "INSERT INTO source (id,event_key,content,timestamp,player_id,kind,speaker,"
                "session_id,hearsay,hop,metadata,checksum) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (source_id, event_key, content, timestamp, player_id, kind, speaker,
                 session_id or source_id, int(hearsay), hop, payload,
                 hashlib.sha256(content.encode('utf-8')).hexdigest()))
            self._conn.execute("INSERT INTO processing (source_id,state) VALUES (?, 'pending')",
                               (source_id,))
            self.events.insert(source_id, context, observed_at)
            self._index(source_id, content)
            return source_id

    def _index(self, source_id: str, content: str) -> None:
        for start in range(0, max(1, len(content)), self.CHUNK_SIZE - self.CHUNK_OVERLAP):
            end = min(start + self.CHUNK_SIZE, len(content))
            terms = ' '.join(search_terms(content[start:end]))
            cur = self._conn.execute(
                "INSERT INTO chunk (source_id,start,end,terms) VALUES (?,?,?,?)",
                (source_id, start, end, terms))
            self._conn.execute("INSERT INTO source_fts(rowid,terms) VALUES (?,?)",
                               (cur.lastrowid, terms))
            if end == len(content):
                break

    @staticmethod
    def _record(row) -> ArchiveRecord:
        return ArchiveRecord(
            row['id'], row['sequence'], row['content'], row['timestamp'],
            row['player_id'], row['kind'], row['speaker'], row['session_id'],
            bool(row['hearsay']), row['hop'], json.loads(row['metadata']),
            row['state'], row['attempts'], row['error'])

    _SELECT = "SELECT s.*,p.state,p.attempts,p.error FROM source s JOIN processing p ON p.source_id=s.id"

    def get(self, source_id: str) -> ArchiveRecord | None:
        with self._lock:
            row = self._conn.execute(self._SELECT + " WHERE s.id=?", (source_id,)).fetchone()
        return self._record(row) if row else None

    def query_events(self, scope: EventScope, query: EventQuery, *, limit: int = 32,
                     cursor: EventCursor | None = None) -> EventPage:
        return self.events.query(scope, query, limit=limit, cursor=cursor)

    def count_events(self, scope: EventScope, query: EventQuery) -> int:
        return self.events.count(scope, query)

    def read_event_source(self, source_id: str, scope: EventScope) -> ArchiveRecord | None:
        with self._lock:
            if self.events.visible(source_id, scope) is None:
                return None
            return self.get(source_id)

    def is_unscoped(self, source_id: str) -> bool:
        with self._lock:
            return self._conn.execute('SELECT 1 FROM event WHERE source_id=? '
                'AND instance_id IS NULL', (source_id,)).fetchone() is not None

    def set_state(self, source_id: str, state: str, error: str = "") -> None:
        if state not in ('pending', 'done'):
            raise ValueError("不支持的原文处理状态")
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE processing SET state=?,error=?,attempts=attempts+? WHERE source_id=?",
                (state, error[:1000], int(bool(error)), source_id))

    def pending(self, limit: int = 20) -> list[ArchiveRecord]:
        with self._lock:
            rows = self._conn.execute(self._SELECT +
                " WHERE p.state='pending' ORDER BY s.sequence LIMIT ?",
                (max(0, min(limit, 1000)),)).fetchall()
        return [self._record(row) for row in rows]

    @staticmethod
    def _scope(player_id: str | None, include_shared: bool) -> tuple[str, list]:
        legacy = (' AND NOT EXISTS (SELECT 1 FROM event e WHERE e.source_id=s.id '
                  'AND e.instance_id IS NOT NULL)')
        if player_id is None:
            return "s.player_id IS NULL" + legacy, []
        if include_shared:
            return "(s.player_id=? OR s.player_id IS NULL)" + legacy, [player_id]
        return "s.player_id=?" + legacy, [player_id]

    def search(self, query: str, *, player_id: str | None = None,
               include_shared: bool = False, after: float | None = None,
               before: float | None = None, limit: int = 8) -> list[dict]:
        """有界返回原文片段；全文索引在数据库中检索，不编码所有历史。"""
        limit = max(0, min(limit, 64))
        if not limit:
            return []
        scope, args = self._scope(player_id, include_shared)
        where = [scope]
        if after is not None:
            where.append("s.timestamp>=?")
            args.append(after)
        if before is not None:
            where.append("s.timestamp<=?")
            args.append(before)
        terms = search_terms(query)
        # 双字和完整英文词优先，单字兜底；表达式只由转义后的词生成。
        strong = [t for t in terms if len(t) > 1]
        terms = (strong or terms)[:48]
        if query.strip() and not terms:
            return []
        match = ' OR '.join('"' + t.replace('"', '""') + '"' for t in terms)
        if match:
            sql = ("SELECT s.id,c.start,c.end,bm25(source_fts) AS rank "
                   "FROM source_fts JOIN chunk c ON c.id=source_fts.rowid "
                   "JOIN source s ON s.id=c.source_id WHERE source_fts MATCH ? AND " +
                   ' AND '.join(where) + " ORDER BY rank,s.sequence DESC LIMIT ?")
            args = [match, *args, limit * 4]
        else:
            sql = ("SELECT s.id,c.start,c.end,0 AS rank FROM chunk c "
                   "JOIN source s ON s.id=c.source_id WHERE " + ' AND '.join(where) +
                   " ORDER BY s.timestamp DESC,s.sequence DESC,c.start LIMIT ?")
            args.append(limit * 4)
        with self._lock:
            rows = self._conn.execute(sql, args).fetchall()
            out, seen = [], set()
            for row in rows:
                if row['id'] in seen:
                    continue
                seen.add(row['id'])
                rec = self.get(row['id'])
                out.append({'id': rec.id, 'archive_id': self.identity,
                            'content': rec.content[row['start']:row['end']],
                            'start': row['start'], 'end': row['end'],
                            'timestamp': rec.timestamp, 'player_id': rec.player_id,
                            'kind': rec.kind, 'speaker': rec.speaker,
                            'session_id': rec.session_id, 'hearsay': rec.hearsay,
                            'hop': rec.hop, 'score': -row['rank']})
                if len(out) == limit:
                    break
            return out

    def neighbors(self, source_id: str, *, player_id: str | None = None,
                  include_shared: bool = False, before: float | None = None,
                  radius: int = 1) -> list[ArchiveRecord]:
        rec = self.get(source_id)
        if rec is None:
            return []
        scope, args = self._scope(player_id, include_shared)
        # session + sequence 窗口，防止跨会话/跨关系展开。
        sql = self._SELECT + " WHERE " + scope + " AND s.session_id=? AND s.sequence BETWEEN ? AND ?"
        radius = max(0, min(radius, 5))
        args += [rec.session_id, rec.sequence - radius, rec.sequence + radius]
        if before is not None:
            sql += " AND s.timestamp<=?"
            args.append(before)
        with self._lock:
            rows = self._conn.execute(sql + " ORDER BY s.sequence", args).fetchall()
        return [self._record(row) for row in rows]

    def count(self) -> int:
        with self._lock:
            return self._conn.execute("SELECT COUNT(*) FROM source").fetchone()[0]

    def rebuild_index(self) -> None:
        with self._lock, self._conn:
            self._conn.execute("DELETE FROM source_fts")
            self._conn.execute("DELETE FROM chunk")
            cursor = self._conn.execute("SELECT id,content FROM source ORDER BY sequence")
            for row in cursor:
                self._index(row['id'], row['content'])

    def backup(self, path: str) -> None:
        with self._lock:
            target = sqlite3.connect(path)
            try:
                self._conn.backup(target)
            finally:
                target.close()

    def close(self) -> None:
        with self._lock:
            self._conn.close()
