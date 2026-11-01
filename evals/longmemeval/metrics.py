"""LongMemEval 官方检索口径的二值 recall / NDCG；不依赖引擎。"""
from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from typing import Any

from .dataset import Question, RetrievedTurn

DEFAULT_KS = (5, 10, 50)


def _dcg(relevances: Sequence[int], k: int) -> float:
    values = list(relevances)[:k]
    if not values:
        return 0.0
    return values[0] + sum(value / math.log2(i + 1)
                           for i, value in enumerate(values[1:], start=1))


def _ndcg(ranked: Sequence[str], correct: set[str], k: int) -> float | None:
    if not correct:
        return None
    actual = _dcg([1 if item in correct else 0 for item in ranked[:k]], k)
    ideal = _dcg([1] * min(len(correct), k), k)
    return actual / ideal if ideal else None


def _urn_metrics(ranked: Sequence[str], correct: set[str], k: int) -> dict[str, float | None]:
    top = set(ranked[:k])
    if not correct:
        return {'recall_all': None, 'recall_any': None, 'ndcg_any': None}
    return {
        'recall_all': float(correct <= top),
        'recall_any': float(bool(correct & top)),
        'ndcg_any': _ndcg(ranked, correct, k),
    }


def _unique_sessions(retrieved: Iterable[RetrievedTurn]) -> list[str]:
    seen, ordered = set(), []
    for turn in retrieved:
        if turn.session_id not in seen:
            seen.add(turn.session_id)
            ordered.append(turn.session_id)
    return ordered


def evaluate_question(question: Question, retrieved: Sequence[RetrievedTurn],
                      ks: Sequence[int] = DEFAULT_KS) -> dict[str, Any]:
    ranked_turns = [turn.turn_key for turn in retrieved]
    ranked_sessions = _unique_sessions(retrieved)
    correct_turns = set(question.evidence_turns())
    correct_sessions = set(question.answer_session_ids)
    turn: dict[str, float | None] = {}
    session: dict[str, float | None] = {}
    for k in ks:
        turn.update({f'{name}@{k}': value
                     for name, value in _urn_metrics(ranked_turns, correct_turns, k).items()})
        session.update({f'{name}@{k}': value
                        for name, value in _urn_metrics(ranked_sessions, correct_sessions, k).items()})
    return {
        'question_id': question.question_id,
        'question_type': question.question_type,
        'turn_count': question.turn_count,
        'session_count': len(question.sessions),
        'correct_turns': len(correct_turns),
        'correct_sessions': len(correct_sessions),
        'turn': turn,
        'session': session,
    }


def _metric(values: Iterable[float | None]) -> dict[str, float | int | None]:
    valid = [v for v in values if v is not None]
    return {'mean': sum(valid) / len(valid) if valid else None, 'n': len(valid)}


def _group(per_question: Sequence[dict[str, Any]], ks: Sequence[int]) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in per_question:
        groups.setdefault(row['question_type'], []).append(row)
    out = {}
    for question_type, rows in sorted(groups.items()):
        out[question_type] = {
            'questions': len(rows),
            'turn': {f'{name}@{k}': _metric(row['turn'][f'{name}@{k}'] for row in rows)
                     for k in ks for name in ('recall_all', 'recall_any', 'ndcg_any')},
            'session': {f'{name}@{k}': _metric(row['session'][f'{name}@{k}'] for row in rows)
                        for k in ks for name in ('recall_all', 'recall_any', 'ndcg_any')},
        }
    return out


def summarize(per_question: Sequence[dict[str, Any]],
              ks: Sequence[int] = DEFAULT_KS) -> dict[str, Any]:
    def flat(section: str) -> dict[str, Any]:
        names = (f'{name}@{k}' for k in ks for name in ('recall_all', 'recall_any', 'ndcg_any'))
        return {name: _metric(row[section][name] for row in per_question)
                for name in names}

    return {
        'questions': len(per_question),
        'turn': flat('turn'),
        'session': flat('session'),
        'by_type': _group(per_question, ks),
    }
