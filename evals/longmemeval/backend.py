"""LongMemEval 与记忆层之间的窄适配器；只依赖公开 MemoryStore API。"""
from __future__ import annotations

from typing import Protocol

from game_agent.memory import MemoryRecord, MemoryStore
from game_agent.models.embeddings import Embedder, HashEmbedder, cosine_similarity

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

    def _embed_chunk(self, texts: list[str]) -> None:
        try:
            vectors = self._base.embed(texts)
        except RuntimeError:
            if len(texts) == 1:
                raise
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


RETRIEVAL_MODES = ('memory', 'relevance', 'session')


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

    def retrieve(self, question: Question, top_k: int) -> tuple[RetrievedTurn, ...]:
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
