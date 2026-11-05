"""混合召回、索引补建和来源归并；不获取 NPC 或 World。"""
from __future__ import annotations

import hashlib
import copy
import json
import math
import time

from .events import EventQuery
from .hybrid import HybridResult, fuse_rankings
from .organization import validate_limit


def normalize(vector, dimension):
    values = list(vector)
    if len(values) != dimension or dimension < 1 or any(
            isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v)
            for v in values):
        raise ValueError('嵌入数量、维度或数值不合法')
    norm = math.sqrt(sum(v * v for v in values))
    if not math.isfinite(norm):
        raise ValueError('嵌入范数不合法')
    return [v / norm for v in values] if norm else values


class HybridRetriever:
    def __init__(self, archive, repository, embedder, version):
        self.archive, self.repository, self.embedder = archive, repository, embedder
        self.index, self.version = archive.retrieval, version

    def _key(self, dimension):
        endpoint = getattr(self.embedder, 'endpoint', None)
        identity = [type(self.embedder).__module__, type(self.embedder).__qualname__,
                    dimension, self.version, getattr(endpoint, 'base_url', None),
                    getattr(endpoint, 'model', None)]
        return hashlib.sha256(json.dumps(identity, ensure_ascii=False).encode()).hexdigest()

    def _index(self, scope, dimension, key, limit):
        rows = self.index.missing(scope, key, limit=limit)
        errors, indexed = [], 0
        batch, chars = [], 0
        batches = []
        for row in rows:
            if batch and (chars + len(row['content']) > 7000 or len(batch) >= 16):
                batches.append(batch)
                batch, chars = [], 0
            batch.append(row)
            chars += len(row['content'])
        if batch:
            batches.append(batch)
        for batch in batches:
            try:
                vectors = self.embedder.embed([r['content'] for r in batch])
                if len(vectors) != len(batch):
                    raise ValueError('嵌入返回数量与片段不符')
                vectors = [normalize(v, dimension) for v in vectors]
            except Exception as exc:
                errors.append({'stage': 'index_embedding', 'type': type(exc).__name__})
                break
            # 数据库和权限错误不作为模型不可用吞掉。
            self.index.save_vectors(batch, vectors, key, dimension)
            indexed += len(batch)
        remaining = self.index.remaining(scope, key)
        return {'indexed': indexed, 'remaining': remaining, 'complete': not errors and remaining == 0,
                'model_key': key, 'errors': errors}

    def index_archive(self, scope, *, limit=256):
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 4096:
            raise ValueError('索引批次须在 1 到 4096 之间')
        try:
            dimension = self.embedder.dim
            if isinstance(dimension, bool) or not isinstance(dimension, int) or dimension < 1:
                raise ValueError('嵌入维度不合法')
        except Exception as exc:
            return {'indexed': 0, 'remaining': None, 'complete': False,
                    'errors': [{'stage': 'embedding_dimension', 'type': type(exc).__name__}]}
        return self._index(scope, dimension, self._key(dimension), limit)

    def _hint_record(self, source_id, scope):
        memory_id = self.repository.projected_id(source_id)
        rec = self.repository.get_record(memory_id) if memory_id is not None else None
        if rec is None or not rec.valid or rec.timestamp > scope.as_of or rec.confidence <= 0:
            return None
        allowed = (rec.player_id is None if scope.player_id is None else
                   rec.player_id == scope.player_id or (scope.include_shared and rec.player_id is None))
        return rec if allowed and rec.type in ('reflection', 'identity', 'episode') else None

    def _raw_accept(self, source_id):
        """迁移前的摘要快照也不能作为独立原始经历重新出现。"""
        memory_id = self.index.legacy_memory_id(source_id)
        if memory_id is None:
            return True
        rec = self.repository.get_record(memory_id)
        return rec is not None and rec.valid and rec.type not in ('reflection','identity','episode','plan')

    def _hint_sources(self, source_id, scope, filters, limit):
        root = self._hint_record(source_id, scope)
        stack = [(i, 0) for i in root.evidence[:128]] if root else []
        seen, sources = set(), {}
        while stack and len(seen) < 128 and len(sources) < limit:
            memory_id, depth = stack.pop(0)
            if memory_id in seen:
                continue
            seen.add(memory_id)
            rec = self.repository.get_record(memory_id)
            if rec is None or not rec.valid or rec.timestamp > scope.as_of:
                continue
            allowed = (rec.player_id is None if scope.player_id is None else
                rec.player_id == scope.player_id or (scope.include_shared and rec.player_id is None))
            if not allowed:
                continue
            for sid in self.repository.sources(memory_id):
                candidate = self.index.source_candidate(sid, scope, filters)
                if candidate is not None and self._raw_accept(sid):
                    sources.setdefault(sid, dict(candidate, hint_ids=[source_id]))
                    if len(sources) == limit:
                        break
            if depth < 3:
                stack.extend((i, depth + 1) for i in rec.evidence[:128])
        return list(sources.values())

    def retrieve(self, query, scope, *, filters=EventQuery(), top_k=8, candidate_k=32,
                 mode='hybrid', index_limit=64, neighbor_radius=0, reranker=None):
        validate_limit(top_k)
        validate_limit(candidate_k)
        if candidate_k < top_k or mode not in ('bm25', 'dense', 'hybrid'):
            raise ValueError('候选数须不少于 top_k，mode 必须为 bm25/dense/hybrid')
        if isinstance(index_limit, bool) or not isinstance(index_limit, int) or not 0 <= index_limit <= 4096:
            raise ValueError('查询索引补建数量须在 0 到 4096 之间')
        if isinstance(neighbor_radius, bool) or not isinstance(neighbor_radius, int) or not 0 <= neighbor_radius <= 2:
            raise ValueError('邻文半径须在 0 到 2 之间')
        if not isinstance(query, str) or len(query) > 4000:
            raise ValueError('查询须为不超过 4000 字符的字符串')
        started = time.monotonic()
        # 先执行过滤校验，不能把非法锚点降级为不带范围的检索。
        self.index.source_candidate('', scope, filters)
        diagnostics = {'mode': mode, 'errors': [], 'indexed': 0, 'remaining': None,
                       'dense_complete': None if mode == 'bm25' else False, 'route_hits': {}}
        if not query.strip():
            return HybridResult((), dict(diagnostics, latency_ms=0.0))
        routes = {}
        if mode != 'dense':
            routes['bm25'] = self.index.lexical(query, scope, filters, candidate_k,
                                                accept=self._raw_accept)
        vector, key = None, None
        if mode != 'bm25':
            try:
                vectors = self.embedder.embed([query])
                if len(vectors) != 1 or not vectors[0]:
                    raise ValueError('查询嵌入返回不合法')
                vector = normalize(vectors[0], self.embedder.dim)
                key = self._key(len(vector))
            except Exception as exc:
                diagnostics['errors'].append({'stage': 'query_embedding', 'type': type(exc).__name__})
            if vector is not None:
                progress = self._index(scope, len(vector), key, index_limit)
                diagnostics.update(indexed=progress['indexed'], remaining=progress['remaining'],
                                   dense_complete=progress['complete'])
                diagnostics['errors'].extend(progress['errors'])
                try:
                    routes['dense'] = self.index.dense(vector, key, scope, filters, candidate_k,
                                                        accept=self._raw_accept)
                except ValueError as exc:
                    diagnostics['errors'].append({'stage': 'vector_read', 'type': type(exc).__name__})
                    diagnostics['dense_complete'] = False
                    vector = None
        # 摘要只导航到其引用的原文；实例档案没有对应的旧主库投影。
        if scope.instance_id is None:
            accept = lambda sid: self._hint_record(sid, scope) is not None
            hint_routes = {}
            if mode != 'dense':
                hint_routes['lexical'] = self.index.lexical(
                    query, scope, EventQuery(), candidate_k, derived=True, accept=accept)
            if vector is not None:
                try:
                    hint_routes['dense'] = self.index.dense(vector, key, scope, EventQuery(),
                        candidate_k, derived=True, accept=accept)
                except ValueError as exc:
                    diagnostics['errors'].append({'stage': 'hint_vector_read', 'type': type(exc).__name__})
                    diagnostics['dense_complete'] = False
            hints, seen = [], set()
            for hint in fuse_rankings(hint_routes):
                for candidate in self._hint_sources(hint['source_id'], scope, filters, candidate_k):
                    if candidate['source_id'] not in seen:
                        hints.append(candidate)
                        seen.add(candidate['source_id'])
                if len(hints) >= candidate_k:
                    break
            if hints:
                routes['hint'] = hints[:candidate_k]
        # 显式结构化条件可独立提供候选，不对自然语言中的序号作推断。
        if filters != EventQuery():
            routes['structured'] = self.index.structured(scope, filters, candidate_k,
                                                         accept=self._raw_accept)
        diagnostics['route_hits'] = {name: len(rows) for name, rows in routes.items()}
        candidates = fuse_rankings(routes)[:candidate_k]
        views = []
        for candidate in candidates:
            if not self._raw_accept(candidate['source_id']):
                continue
            view = self.index.view(candidate, scope, filters)
            if view is not None:
                view['archive_id'] = self.archive.identity
                views.append(view)
        if reranker is not None and views:
            scores = list(reranker(query, copy.deepcopy(views)))
            if len(scores) != len(views) or any(isinstance(s, bool) or
                    not isinstance(s, (int, float)) or not math.isfinite(s) for s in scores):
                raise ValueError('重排须返回与候选等长的有限数分数')
            views = [dict(view, rerank_score=score) for view, score in zip(views, scores)]
            views.sort(key=lambda v: -v['rerank_score'])
        hits = views[:top_k]
        neighbors, seen = [], {hit['source_id'] for hit in hits}
        if neighbor_radius:
            for hit in hits:
                for candidate in self.index.neighbors(hit, scope, filters, neighbor_radius):
                    if candidate['source_id'] in seen or not self._raw_accept(candidate['source_id']):
                        continue
                    view = self.index.view(candidate, scope, filters)
                    if view is not None:
                        view['archive_id'] = self.archive.identity
                        neighbors.append(view)
                        seen.add(view['source_id'])
                    if len(neighbors) >= top_k:
                        break
                if len(neighbors) >= top_k:
                    break
        diagnostics['latency_ms'] = round((time.monotonic() - started) * 1000, 3)
        return HybridResult(tuple(hits), diagnostics, tuple(neighbors))
