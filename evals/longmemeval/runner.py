"""LongMemEval 批量召回评测编排；不关心具体嵌入或 CLI。"""
from __future__ import annotations

from typing import Any, Sequence

from .backend import MemoryBackend
from .dataset import Question
from .metrics import DEFAULT_KS, evaluate_question, summarize


def evaluate(questions: Sequence[Question], backend: MemoryBackend, *,
             top_k: int = 50, ks: Sequence[int] = DEFAULT_KS) -> dict[str, Any]:
    per_question = []
    for question in questions:
        retrieved = backend.retrieve(question, top_k)
        row = evaluate_question(question, retrieved, ks)
        row['question'] = question.question
        row['retrieved'] = [
            {
                'session_id': turn.session_id,
                'turn_index': turn.turn_index,
                'role': turn.role,
                'has_answer': turn.has_answer,
                'score': round(turn.score, 6),
                'content': turn.content[:500],
            }
            for turn in retrieved
        ]
        per_question.append(row)
    return {
        'summary': summarize(per_question, ks),
        'per_question': per_question,
    }
