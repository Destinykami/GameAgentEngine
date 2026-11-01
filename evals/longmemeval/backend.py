"""LongMemEval 与记忆层之间的窄适配器；只依赖公开 MemoryStore API。"""
from __future__ import annotations

from typing import Protocol

from game_agent.memory import MemoryRecord, MemoryStore
from game_agent.models.embeddings import Embedder, HashEmbedder

from .dataset import Question, RetrievedTurn


class MemoryBackend(Protocol):
    def retrieve(self, question: Question, top_k: int) -> tuple[RetrievedTurn, ...]: ...


class GameAgentMemoryBackend:
    """每题一个内存 MemoryStore；turn 作为 observation 原样写入，不经过 NPC。

    不使用 NPC.observe 是有意的：LongMemEval 的证据是原始 turn，观察去重、
    重要性打分、反思阈值和关系流过滤都会改变召回口径。
    """

    def __init__(self, embedder: Embedder | None = None) -> None:
        self.embedder = embedder or HashEmbedder()

    def retrieve(self, question: Question, top_k: int) -> tuple[RetrievedTurn, ...]:
        store = MemoryStore(self.embedder)
        turns: dict[int, RetrievedTurn] = {}
        try:
            for session in question.sessions:
                for index, turn in enumerate(session.turns):
                    memory_id = store.add(MemoryRecord(
                        content=f'[{turn.role}] {turn.content}',
                        timestamp=session.at,
                        importance=5.0,
                        type='observation',
                        player_id=None,
                    ))
                    turns[memory_id] = RetrievedTurn(
                        session.session_id, index, turn.role, turn.content,
                        turn.has_answer, session.at, 0.0)
            rows = store.retrieve(question.question, now=question.at,
                                  top_k=top_k, mark_accessed=False,
                                  min_relevance=0.0)
            out = []
            for row in rows:
                turn = turns.get(row['id'])
                if turn is None:
                    continue
                out.append(RetrievedTurn(
                    turn.session_id, turn.turn_index, turn.role, turn.content,
                    turn.has_answer, turn.at, float(row.get('score', 0.0))))
            return tuple(out)
        finally:
            store.close()
