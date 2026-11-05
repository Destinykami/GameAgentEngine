"""LongMemEval 批量召回评测编排；不关心具体嵌入或 CLI。"""
from __future__ import annotations

from typing import Any, Sequence
import copy

from .backend import MemoryBackend
from .dataset import Question
from .metrics import DEFAULT_KS, evaluate_question, summarize


def evaluate(questions: Sequence[Question], backend: MemoryBackend, *,
             top_k: int = 50, ks: Sequence[int] = DEFAULT_KS,
             progress=None, on_result=None) -> dict[str, Any]:
    per_question = []
    for index, question in enumerate(questions, start=1):
        retrieved = backend.retrieve(question, top_k)
        row = evaluate_question(question, retrieved, ks)
        row['question'] = question.question
        diagnostics = getattr(backend, 'last_diagnostics', None)
        if diagnostics:
            row['retrieval_diagnostics'] = copy.deepcopy(diagnostics)
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
        if on_result is not None:
            on_result(row)
        if progress is not None:
            progress(index, len(questions), question, row)
    return {
        'summary': summarize(per_question, ks),
        'per_question': per_question,
    }
