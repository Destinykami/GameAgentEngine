"""LongMemEval 与记忆层之间的窄适配器；只依赖公开 MemoryStore API。"""
from __future__ import annotations

from typing import Protocol
import time

from game_agent.memory import MemoryRecord, MemoryStore
from game_agent.models.embeddings import Embedder, HashEmbedder, cosine_similarity
from game_agent.memory.events import EventScope

from .dataset import Question, RetrievedTurn


class _CachedBatchEmbedder(Embedder):
    """先批量编码全部 turn，再让 MemoryStore 的逐条 add 命中缓存。

    LongMemEval-S 有超长 filler turn（最大 76k 字符），必须先截断并按字符预算
    分批；端点仍拒绝时递归二分，避免整题失败。
    """

    def __init__(self, base: Embedder, texts: list[str], *,
                 batch_size: int = 64, max_chars: int = 6000,
                 char_budget: int = 8000) -> None:
        self._base = base
        self._max_chars = max(1, max_chars)
        self._char_budget = max(1, char_budget)
        self._batch_size = max(1, batch_size)
        self._cache: dict[str, list[float]] = {}
        unique = list(dict.fromkeys(self._clip(text) for text in texts))
        for batch in self._batches(unique):
            self._embed_chunk(batch)
        self._dim = len(next(iter(self._cache.values()))) if self._cache else base.dim

    def _clip(self, text: str) -> str:
        return text[:self._max_chars]

    def _batches(self, texts: list[str]):
        batch: list[str] = []
        size = 0
        for text in texts:
            if batch and (len(batch) >= self._batch_size or size + len(text) > self._char_budget):
                yield batch
                batch, size = [], 0
            batch.append(text)
            size += len(text)
        if batch:
            yield batch

    def _embed_single(self, text: str) -> None:
        """单段超长时逐步缩短前缀；缓存仍以原截断文本为键。"""
        limit = len(text)
        while limit > 0:
            try:
                vectors = self._base.embed([text[:limit]])
            except RuntimeError:
                limit //= 2
                continue
            if len(vectors) != 1:
                raise ValueError('embedding 返回数量与输入不一致')
            self._cache[text] = vectors[0]
            return
        raise RuntimeError(f'embedding 单段重试失败: {text[:64]!r}')

    def _embed_chunk(self, texts: list[str]) -> None:
        try:
            vectors = self._base.embed(texts)
        except RuntimeError:
            if len(texts) == 1:
                self._embed_single(texts[0])
                return
            middle = len(texts) // 2
            self._embed_chunk(texts[:middle])
            self._embed_chunk(texts[middle:])
            return
        if len(vectors) != len(texts):
            raise ValueError('embedding 返回数量与输入不一致')
        self._cache.update(zip(texts, vectors))

    @property
    def dim(self) -> int:
        return self._dim

    def embed(self, texts):
        clipped = [self._clip(text) for text in texts]
        missing = list(dict.fromkeys(text for text in clipped if text not in self._cache))
        if missing:
            for batch in self._batches(missing):
                self._embed_chunk(batch)
        return [self._cache[text] for text in clipped]


RETRIEVAL_MODES = ('memory', 'relevance', 'session', 'bm25', 'dense', 'hybrid')


class MemoryBackend(Protocol):
    def retrieve(self, question: Question, top_k: int) -> tuple[RetrievedTurn, ...]: ...


class GameAgentMemoryBackend:
    """每题一个内存 MemoryStore；turn 作为 observation 原样写入，不经过 NPC。

    不使用 NPC.observe 是有意的：LongMemEval 的证据是原始 turn，观察去重、
    重要性打分、反思阈值和关系流过滤都会改变召回口径。
    """

    def __init__(self, embedder: Embedder | None = None, *, batch_size: int = 64,
                 retrieval: str = 'memory') -> None:
        if retrieval not in RETRIEVAL_MODES:
            raise ValueError(f'未知 retrieval: {retrieval}')
        self.embedder = embedder or HashEmbedder()
        self.batch_size = batch_size
        self.retrieval = retrieval
        self.last_diagnostics = {}

    def retrieve(self, question: Question, top_k: int) -> tuple[RetrievedTurn, ...]:
        self.last_diagnostics = {}
        if self.retrieval in ('bm25', 'dense', 'hybrid'):
            return self._hybrid_retrieve(question, top_k)
        contents = [(session, index, turn, f'[{turn.role}] {turn.content}')
                    for session in question.sessions
                    for index, turn in enumerate(session.turns)]
        cached = _CachedBatchEmbedder(self.embedder,
                                      [item[3] for item in contents],
                                      batch_size=self.batch_size)
        store = MemoryStore(cached)
        by_id: dict[int, RetrievedTurn] = {}
        try:
            for session, index, turn, content in contents:
                memory_id = store.add(MemoryRecord(
                    content=content,
                    timestamp=session.at,
                    importance=5.0,
                    type='observation',
                    player_id=None,
                ))
                by_id[memory_id] = RetrievedTurn(
                    session.session_id, index, turn.role, turn.content,
                    turn.has_answer, session.at, 0.0)
            if self.retrieval in ('memory', 'relevance'):
                rows = store.retrieve(
                    question.question, now=question.at, top_k=top_k,
                    mark_accessed=False, min_relevance=0.0,
                    weights=None if self.retrieval == 'memory' else (0.0, 0.0, 1.0))
                out = []
                for row in rows:
                    turn = by_id.get(row['id'])
                    if turn is not None:
                        out.append(RetrievedTurn(
                            turn.session_id, turn.turn_index, turn.role, turn.content,
                            turn.has_answer, turn.at, float(row.get('score', 0.0))))
                return tuple(out)
            # session 聚合：取全部 turn，按 session 内最大 relevance 排序后展开。
            qvec = cached.embed([question.question])[0]
            vectors = cached.embed([f'[{turn.role}] {turn.content}'
                                    for turn in by_id.values()])
            scored = [(cosine_similarity(vector, qvec), turn)
                      for vector, turn in zip(vectors, by_id.values())]
            # session：先按 session 内最大 relevance 排 session，再排 session 内 turn。
            sessions: dict[str, list[tuple[float, RetrievedTurn]]] = {}
            order: dict[str, int] = {}
            for score, turn in scored:
                sessions.setdefault(turn.session_id, []).append((score, turn))
                order.setdefault(turn.session_id, len(order))
            ranked = sorted(sessions, key=lambda sid: (
                -max(score for score, _ in sessions[sid]), order[sid]))
            flat = []
            for sid in ranked:
                flat.extend(sorted(sessions[sid], key=lambda item: item[0], reverse=True))
            return tuple(RetrievedTurn(t.session_id, t.turn_index, t.role, t.content,
                                       t.has_answer, t.at, score)
                         for score, t in flat[:top_k])

        finally:
            store.close()

    def _hybrid_retrieve(self, question: Question, top_k: int) -> tuple[RetrievedTurn, ...]:
        """三种新模式共享同一原文语料与核心入口，不复写融合算法。"""
        if isinstance(top_k, bool) or not isinstance(top_k, int) or not 1 <= top_k <= 128:
            raise ValueError('混合检索评测的 top_k 须在 1 到 128 之间')
        started = time.monotonic()
        store = MemoryStore(self.embedder)
        scope = EventScope(as_of=question.at)
        by_source = {}
        indexed = 0
        try:
            for session in question.sessions:
                for index, turn in enumerate(session.turns):
                    sid = store.archive_input(turn.content, session.at,
                        kind='dialogue_in' if turn.role == 'user' else 'dialogue_out',
                        speaker=turn.role, session_id=session.session_id)
                    store.archive_done(sid)  # 评测只归档，不伪造主库观察或重要性。
                    by_source[sid] = RetrievedTurn(session.session_id, index, turn.role,
                        turn.content, turn.has_answer, session.at, 0.0)
            indexing_started = time.monotonic()
            if self.retrieval != 'bm25':
                while True:
                    progress = store.index_archive(scope, limit=256)
                    if progress['errors']:
                        raise RuntimeError('评测原文向量索引失败，不能报告完整检索结果')
                    indexed += progress['indexed']
                    if progress['complete']:
                        break
                    if progress['indexed'] == 0:
                        raise RuntimeError('评测索引未取得进展')
            indexing_ms = (time.monotonic() - indexing_started) * 1000
            result = store.hybrid_retrieve(question.question, scope, top_k=top_k,
                candidate_k=max(32, top_k), mode=self.retrieval, index_limit=0)
            if self.retrieval != 'bm25' and (
                    not result.diagnostics['dense_complete'] or result.diagnostics['errors']):
                raise RuntimeError('评测向量覆盖不完整或已降级，不能作为成功结果')
            self.last_diagnostics = dict(result.diagnostics,
                indexed_chunks=indexed, indexing_ms=round(indexing_ms, 3),
                pipeline_ms=round((time.monotonic()-started)*1000, 3),
                matches=[{'session_id': by_source[hit['id']].session_id,
                    'turn_index': by_source[hit['id']].turn_index,
                    'start': hit['start'], 'end': hit['end'],
                    'content': hit['content'], 'ranks': hit['ranks']} for hit in result.hits])
            # 指标单位仍为 turn；同来源已在核心归并，旧 QA reader 仍可展开完整 turn。
            return tuple(RetrievedTurn(
                by_source[hit['id']].session_id, by_source[hit['id']].turn_index,
                by_source[hit['id']].role, by_source[hit['id']].content,
                by_source[hit['id']].has_answer, by_source[hit['id']].at, hit['score'])
                for hit in result.hits)
        finally:
            store.close()
