"""LongMemEval 数据模型、日期解析与字段校验；不依赖引擎或网络。"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Turn:
    role: str
    content: str
    has_answer: bool = False


@dataclass(frozen=True)
class Session:
    session_id: str
    at: float
    turns: tuple[Turn, ...]


@dataclass(frozen=True)
class RetrievedTurn:
    session_id: str
    turn_index: int
    role: str
    content: str
    has_answer: bool
    at: float
    score: float

    @property
    def turn_key(self) -> str:
        return f'{self.session_id}#{self.turn_index}'


@dataclass(frozen=True)
class Question:
    question_id: str
    question_type: str
    question: str
    answer: str
    at: float
    sessions: tuple[Session, ...]
    answer_session_ids: frozenset[str]

    @property
    def turn_count(self) -> int:
        return sum(len(session.turns) for session in self.sessions)

    def turn_key(self, session_id: str, turn_index: int) -> str:
        return f'{session_id}#{turn_index}'

    def evidence_turns(self) -> frozenset[str]:
        """turn 级证据：优先 has_answer；缺失时退回 answer_session_ids 的全部 turn。"""
        marked = frozenset(
            self.turn_key(session.session_id, i)
            for session in self.sessions
            for i, turn in enumerate(session.turns) if turn.has_answer)
        if marked:
            return marked
        return frozenset(
            self.turn_key(session.session_id, i)
            for session in self.sessions if session.session_id in self.answer_session_ids
            for i in range(len(session.turns)))


_DATE_PATTERNS = (
    '%Y/%m/%d %H:%M:%S', '%Y/%m/%d %H:%M', '%Y/%m/%d',
    '%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M', '%Y-%m-%d',
)
_WEEKDAY = re.compile(r'\s*\([^)]*\)')


def parse_time(value: str) -> float:
    """解析 LongMemEval 时间串为 UTC 小时；失败直接报错，不静默猜。"""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'非法时间: {value!r}')
    text = _WEEKDAY.sub('', value.strip())
    for pattern in _DATE_PATTERNS:
        try:
            dt = datetime.strptime(text, pattern).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        return dt.timestamp() / 3600.0
    raise ValueError(f'无法解析 LongMemEval 时间: {value!r}')


def _require(row: dict[str, Any], key: str) -> Any:
    if key not in row:
        raise ValueError(f'问题缺少字段 {key}')
    return row[key]


def question_from_dict(row: dict[str, Any]) -> Question:
    qid = str(_require(row, 'question_id'))
    sessions_raw = _require(row, 'haystack_sessions')
    dates = _require(row, 'haystack_dates')
    session_ids = _require(row, 'haystack_session_ids')
    if not isinstance(sessions_raw, list) or not isinstance(dates, list) or not isinstance(session_ids, list):
        raise ValueError(f'{qid}: haystack 字段必须是列表')
    if not (len(sessions_raw) == len(dates) == len(session_ids)):
        raise ValueError(f'{qid}: haystack_sessions/dates/session_ids 长度不一致')
    sessions = []
    for sid, date, turns_raw in zip(session_ids, dates, sessions_raw):
        if not isinstance(sid, str) or not isinstance(turns_raw, list):
            raise ValueError(f'{qid}: session 字段格式错误')
        turns = []
        for raw in turns_raw:
            if not isinstance(raw, dict) or 'role' not in raw or 'content' not in raw:
                raise ValueError(f'{qid}/{sid}: turn 缺少 role/content')
            turns.append(Turn(str(raw['role']), str(raw['content']),
                              bool(raw.get('has_answer', False))))
        if not turns:
            raise ValueError(f'{qid}/{sid}: session 为空')
        sessions.append(Session(sid, parse_time(date), tuple(turns)))
    answer_ids = _require(row, 'answer_session_ids')
    if not isinstance(answer_ids, list):
        raise ValueError(f'{qid}: answer_session_ids 必须是列表')
    known = {session.session_id for session in sessions}
    unknown = set(map(str, answer_ids)) - known
    if unknown:
        raise ValueError(f'{qid}: answer_session_ids 不在 history 中: {sorted(unknown)}')
    answer = row.get('answer', '')
    return Question(
        question_id=qid,
        question_type=str(row.get('question_type', 'unknown')),
        question=str(_require(row, 'question')),
        answer=str(answer),
        at=parse_time(str(_require(row, 'question_date'))),
        sessions=tuple(sessions),
        answer_session_ids=frozenset(map(str, answer_ids)),
    )


def load_questions(path: str | Path) -> tuple[Question, ...]:
    with open(path, encoding='utf-8') as stream:
        raw = json.load(stream)
    if isinstance(raw, dict):
        raw = raw.get('questions', raw.get('data'))
    if not isinstance(raw, list):
        raise ValueError('LongMemEval 文件必须是问题列表')
    questions = tuple(question_from_dict(row) for row in raw)
    ids = [q.question_id for q in questions]
    if len(ids) != len(set(ids)):
        raise ValueError('LongMemEval 存在重复 question_id')
    return questions
