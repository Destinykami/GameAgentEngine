"""档案片段持久索引与流式扫描；编码调用由上层组织。"""
from __future__ import annotations
import hashlib
import json
import math
import struct
from contextlib import closing
from .events import EventQuery


class ArchiveRetrieval:
    def __init__(self, connection, lock, events, tokenize):
        self._conn, self._lock, self._events = connection, lock, events
        self._tokenize = tokenize
        with lock, connection:
            connection.execute('''CREATE TABLE IF NOT EXISTS chunk_vector (
                chunk_id INTEGER NOT NULL, model_key TEXT NOT NULL,
                content_hash TEXT NOT NULL, dimension INTEGER NOT NULL,
                vector BLOB NOT NULL, PRIMARY KEY(chunk_id, model_key))''')

    def _conditions(self, scope, filters, *, derived=None):
        where, args = self._events.conditions(scope, filters)
        if scope.instance_id is None:
            where.append('e.instance_id IS NULL')
            with self._lock:
                for sid in (filters.after_event, filters.before_event):
                    if sid is not None and self._conn.execute(
                            'SELECT 1 FROM event WHERE source_id=? AND instance_id IS NOT NULL',
                            (sid,)).fetchone():
                        raise ValueError('锚点不可见或不存在')
        if derived is True:
            where.append("s.kind IN ('reflection','identity','episode','legacy_snapshot')")
        elif derived is False:
            where.extend(["e.evidence_kind!='derived'",
                          "s.kind NOT IN ('reflection','identity','episode','plan')"])
        return ' AND '.join(where), args

    _FROM = (' FROM chunk c JOIN source s ON s.id=c.source_id '
             'JOIN event e ON e.source_id=s.id ')
    _FIELDS = 'c.id AS chunk_id,c.source_id,c.start,c.end,s.sequence'

    def _rows(self, sql, args):
        """分批释放档案锁，避免证据回查与主库写入形成反向锁顺序。"""
        with self._lock:
            cursor = self._conn.execute(sql, args)
        try:
            while True:
                with self._lock:
                    rows = cursor.fetchmany(128)
                if not rows:
                    break
                yield from rows
        finally:
            with self._lock:
                cursor.close()

    def missing(self, scope, model_key, *, limit):
        where, args = self._conditions(scope, EventQuery())
        with self._lock:
            rows = self._conn.execute('SELECT ' + self._FIELDS +
                ',substr(s.content,c.start+1,c.end-c.start) AS content' + self._FROM +
                'WHERE ' + where + ' AND NOT EXISTS (SELECT 1 FROM chunk_vector v '
                'WHERE v.chunk_id=c.id AND v.model_key=?) ORDER BY c.id LIMIT ?',
                [*args, model_key, limit]).fetchall()
        return [dict(r) for r in rows]

    def remaining(self, scope, model_key):
        where, args = self._conditions(scope, EventQuery())
        with self._lock:
            return self._conn.execute('SELECT COUNT(*)' + self._FROM +
                'WHERE ' + where + ' AND NOT EXISTS (SELECT 1 FROM chunk_vector v '
                'WHERE v.chunk_id=c.id AND v.model_key=?)', [*args, model_key]).fetchone()[0]

    def save_vectors(self, rows, vectors, model_key, dimension):
        with self._lock, self._conn:
            for row, vector in zip(rows, vectors):
                current = self._conn.execute('SELECT substr(s.content,c.start+1,c.end-c.start) '
                    'FROM chunk c JOIN source s ON s.id=c.source_id '
                    'WHERE c.id=? AND c.source_id=? AND c.start=? AND c.end=?',
                    (row['chunk_id'], row['source_id'], row['start'], row['end'])).fetchone()
                if current is None or current[0] != row['content']:
                    continue
                self._conn.execute('INSERT OR REPLACE INTO chunk_vector VALUES (?,?,?,?,?)',
                    (row['chunk_id'], model_key,
                     hashlib.sha256(row['content'].encode()).hexdigest(), dimension,
                     struct.pack('<' + 'f' * dimension, *vector)))

    def lexical(self, query, scope, filters, limit, *, derived=False, accept=None):
        terms = self._tokenize(query)
        terms = ([t for t in terms if len(t) > 1] or terms)[:48]
        if not terms:
            return []
        match = ' OR '.join('"' + t.replace('"', '""') + '"' for t in terms)
        where, args = self._conditions(scope, filters, derived=derived)
        result, seen = [], set()
        sql = ('SELECT ' + self._FIELDS +
                ',bm25(source_fts) AS lexical_score FROM source_fts '
                'JOIN chunk c ON c.id=source_fts.rowid JOIN source s ON s.id=c.source_id '
                'JOIN event e ON e.source_id=s.id WHERE source_fts MATCH ? AND ' + where +
                ' ORDER BY lexical_score,s.sequence DESC,c.start')
        with closing(self._rows(sql, [match, *args])) as rows:
            for row in rows:
                item = dict(row)
                sid = item['source_id']
                if sid in seen or (accept is not None and not accept(sid)):
                    continue
                seen.add(sid)
                result.append(item)
                if len(result) >= limit:
                    break
        return result

    def dense(self, vector, model_key, scope, filters, limit, *, derived=False,
              accept=None, min_similarity=.1):
        where, args = self._conditions(scope, filters, derived=derived)
        best, invalid = {}, None
        sql = ('SELECT ' + self._FIELDS +
                ',v.dimension,v.vector' + self._FROM +
                'JOIN chunk_vector v ON v.chunk_id=c.id WHERE v.model_key=? AND ' + where)
        with closing(self._rows(sql, [model_key, *args])) as rows:
            for row in rows:
                if row['dimension'] != len(vector) or len(row['vector']) != 4 * len(vector):
                    invalid = row['chunk_id']
                    break
                values = struct.unpack('<' + 'f' * len(vector), row['vector'])
                if not all(math.isfinite(v) for v in values):
                    invalid = row['chunk_id']
                    break
                score = sum(a * b for a, b in zip(vector, values))
                if score < min_similarity:
                    continue
                sid = row['source_id']
                if accept is not None and not accept(sid):
                    continue
                item = {key: row[key] for key in ('chunk_id','source_id','start','end','sequence')}
                item['dense_score'] = score
                old = best.get(sid)
                if old is not None:
                    if (score, -item['start']) > (old['dense_score'], -old['start']):
                        best[sid] = item
                else:
                    best[sid] = item
                    if len(best) > limit:
                        worst = min(best, key=lambda key: (
                            best[key]['dense_score'], best[key]['sequence'], -best[key]['start']))
                        del best[worst]
        if invalid is not None:
            with self._lock, self._conn:
                self._conn.execute('DELETE FROM chunk_vector WHERE chunk_id=? AND model_key=?',
                                   (invalid, model_key))
            raise ValueError('持久向量损坏，已清除，后续查询可补建')
        return sorted(best.values(), key=lambda r: (-r['dense_score'], -r['sequence'], r['start']))

    def source_candidate(self, source_id, scope, filters):
        where, args = self._conditions(scope, filters, derived=False)
        with self._lock:
            row = self._conn.execute('SELECT ' + self._FIELDS + self._FROM +
                'WHERE s.id=? AND ' + where + ' ORDER BY c.start LIMIT 1',
                [source_id, *args]).fetchone()
        return dict(row) if row else None

    def legacy_memory_id(self, source_id):
        with self._lock:
            row = self._conn.execute("SELECT metadata FROM source WHERE id=? AND kind='legacy_snapshot'",
                                     (source_id,)).fetchone()
        return json.loads(row[0]).get('legacy_memory_id') if row else None

    def structured(self, scope, filters, limit, *, accept=None):
        where, args = self._conditions(scope, filters, derived=False)
        column = {'sequence': 's.sequence', 'occurred_at': 'e.occurred_at',
                  'observed_at': 'e.observed_at'}[filters.order_by]
        direction = 'DESC' if filters.descending else 'ASC'
        sql = ('SELECT ' + self._FIELDS + self._FROM +
                'WHERE ' + where + ' AND c.start=0 ORDER BY ' + column + ' ' + direction +
                ',s.sequence ' + direction)
        result = []
        with closing(self._rows(sql, args)) as rows:
            for row in rows:
                if accept is None or accept(row['source_id']):
                    result.append(dict(row))
                    if len(result) >= limit:
                        break
        return result

    def view(self, candidate, scope, filters):
        where, args = self._conditions(scope, filters, derived=False)
        with self._lock:
            row = self._conn.execute('SELECT ' + self._FIELDS +
                ',substr(s.content,c.start+1,c.end-c.start) AS content,s.timestamp,s.player_id,'
                's.kind,s.speaker,s.session_id,s.hearsay,s.hop,e.evidence_kind,'
                'length(s.content) AS full_length' + self._FROM +
                'WHERE c.id=? AND ' + where, [candidate['chunk_id'], *args]).fetchone()
        if row is None:
            return None
        item = dict(row)
        full_length = item.pop('full_length')
        item.update(id=item['source_id'], category='raw_archive', type='original', usage='recall',
                    hearsay=bool(item['hearsay']),
                    truncated=item['start'] > 0 or item['end'] < full_length,
                    score=candidate['score'], ranks=dict(candidate['ranks']),
                    hint_ids=candidate.get('hint_ids', []))
        if 'neighbor_of' in candidate:
            item['neighbor_of'] = candidate['neighbor_of']
        return item

    def neighbors(self, candidate, scope, filters, radius):
        where, args = self._conditions(scope, filters, derived=False)
        with self._lock:
            anchor = self._conn.execute('SELECT session_id,sequence FROM source WHERE id=?',
                                       (candidate['source_id'],)).fetchone()
            if anchor is None:
                return []
            rows = self._conn.execute('SELECT ' + self._FIELDS + self._FROM +
                'WHERE ' + where + ' AND s.session_id=? AND s.sequence BETWEEN ? AND ? '
                'AND c.start=0 ORDER BY s.sequence',
                [*args, anchor['session_id'], anchor['sequence']-radius,
                 anchor['sequence']+radius]).fetchall()
        return [dict(row, score=candidate['score'], ranks={}, neighbor_of=candidate['source_id'])
                for row in rows if row['source_id'] != candidate['source_id']]
