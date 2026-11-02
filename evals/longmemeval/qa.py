"""LongMemEval reader + LLM judge；只依赖数据模型和窄 LLM ask 协议。"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, Sequence

from .dataset import Question

READER_SYSTEM = '你是一个只依据给定对话历史回答问题的助手。'
JUDGE_SYSTEM = '你是一个严格的答案判定器。只输出 yes 或 no。'


class Reader(Protocol):
    def answer(self, question: str, context: str, *, question_type: str = '') -> str: ...


class Judge(Protocol):
    def correct(self, question: Question, response: str) -> bool: ...


@dataclass
class LLMReader:
    llm: Any
    max_tokens: int = 256

    def answer(self, question: str, context: str, *, question_type: str = '') -> str:
        if question_type == 'single-session-preference':
            task = ('这是偏好推荐题。请利用历史中用户明确说过的偏好、品牌、工具和限制，'
                    '给出具体建议；不要因为历史没有逐字列出推荐资源就回答不知道。')
        elif question_type == 'multi-session':
            task = ('这是多会话题。请合并所有相关会话中的证据后再回答；'
                    '如果要求计数或列举，逐项核对，不要只依据最近一段。')
        elif question_type == 'temporal-reasoning':
            task = ('这是时间推理题。请使用会话日期计算时间差或先后顺序，'
                    '给出最终答案；必要时在心里完成中间计算，不要解释过程。')
        else:
            task = ('请只依据历史回答问题；历史中确实没有的信息才回答 "I don\'t know"。')
        prompt = (
            f'{task}答案要简短，不要解释。\n\n'
            f'历史:\n{context}\n\n问题: {question}\n答案:')
        return self.llm.ask(prompt, system=READER_SYSTEM, think=False,
                            temperature=0.0, max_tokens=self.max_tokens).strip()


def _session_id(item) -> str:
    return item.session_id if hasattr(item, 'session_id') else item['session_id']


def _item_field(item, name, default=None):
    return getattr(item, name) if hasattr(item, name) else item.get(name, default)


def _selected_turns(question: Question, retrieved: Sequence, top_turns: int):
    sessions = {session.session_id: session for session in question.sessions}
    selected, seen = [], set()
    for item in retrieved:
        sid = _session_id(item)
        index = _item_field(item, 'turn_index')
        session = sessions.get(sid)
        if session is None or index is None or not 0 <= index < len(session.turns):
            continue
        key = (sid, index)
        if key in seen:
            continue
        seen.add(key)
        selected.append((session, session.turns[index], item))
        if len(selected) >= top_turns:
            break
    return selected


def build_context(question: Question, retrieved: Sequence, *,
                  top_turns: int = 50, max_chars: int = 40000,
                  max_turn_chars: int = 2000) -> str:
    """按检索顺序展开 top turn，带 session 日期；不展开未命中的 session 内容。"""
    selected = _selected_turns(question, retrieved, top_turns)
    if not selected:
        return '(no retrieved history)'
    lines, used, last_sid = [], 0, None
    for session, turn, _ in selected:
        if session.session_id != last_sid:
            header = f'[session {session.session_id} | {session.date or session.at}]'
            if used + len(header) + 1 > max_chars:
                break
            lines.append(header)
            used += len(header) + 1
            last_sid = session.session_id
        text = f'{turn.role}: {turn.content[:max_turn_chars]}'
        if used + len(text) + 1 > max_chars:
            break
        lines.append(text)
        used += len(text) + 1
    return '\n'.join(lines)


def judge_prompt(question: Question, response: str) -> str:
    if question.question_id.endswith('_abs'):
        return ('I will give you an unanswerable question, an explanation, and a response from a model. '
                'Please answer yes if the model correctly identifies the question as unanswerable. '
                'The model could say that the information is incomplete, or some other information is '
                'given but the asked information is not.\n\n'
                f'Question: {question.question}\n\nExplanation: {question.answer}\n\n'
                f'Model Response: {response}\n\nDoes the model correctly identify the question as '
                'unanswerable? Answer yes or no only.')
    task = question.question_type
    if task in ('single-session-user', 'single-session-assistant', 'multi-session'):
        template = ('I will give you a question, a correct answer, and a response from a model. '
                    'Please answer yes if the response contains the correct answer. Otherwise, answer no. '
                    'If the response is equivalent to the correct answer or contains all the intermediate '
                    'steps to get the correct answer, you should also answer yes. If the response only '
                    'contains a subset of the information required by the answer, answer no. \n\n'
                    'Question: {}\n\nCorrect Answer: {}\n\nModel Response: {}\n\n'
                    'Is the model response correct? Answer yes or no only.')
    elif task == 'temporal-reasoning':
        template = ('I will give you a question, a correct answer, and a response from a model. '
                    'Please answer yes if the response contains the correct answer. Otherwise, answer no. '
                    'If the response is equivalent to the correct answer or contains all the intermediate '
                    'steps to get the correct answer, you should also answer yes. If the response only '
                    'contains a subset of the information required by the answer, answer no. In addition, '
                    'do not penalize off-by-one errors for the number of days. If the question asks for '
                    'the number of days/weeks/months, etc., and the model makes off-by-one errors (e.g., '
                    'predicting 19 days when the answer is 18), the model\'s response is still correct. \n\n'
                    'Question: {}\n\nCorrect Answer: {}\n\nModel Response: {}\n\n'
                    'Is the model response correct? Answer yes or no only.')
    elif task == 'knowledge-update':
        template = ('I will give you a question, a correct answer, and a response from a model. '
                    'Please answer yes if the response contains the correct answer. Otherwise, answer no. '
                    'If the response contains some previous information along with an updated answer, '
                    'the response should be considered as correct as long as the updated answer is the '
                    'required answer.\n\nQuestion: {}\n\nCorrect Answer: {}\n\nModel Response: {}\n\n'
                    'Is the model response correct? Answer yes or no only.')
    elif task == 'single-session-preference':
        template = ('I will give you a question, a rubric for desired personalized response, and a '
                    'response from a model. Please answer yes if the response satisfies the desired '
                    'response. Otherwise, answer no. The model does not need to reflect all the points '
                    'in the rubric. The response is correct as long as it recalls and utilizes the '
                    'user\'s personal information correctly.\n\nQuestion: {}\n\nRubric: {}\n\n'
                    'Model Response: {}\n\nIs the model response correct? Answer yes or no only.')
    else:
        raise ValueError(f'未知 question_type: {task}')
    return template.format(question.question, question.answer, response)


@dataclass
class LLMJudge:
    llm: Any

    def correct(self, question: Question, response: str) -> bool:
        verdict = self.llm.ask(judge_prompt(question, response), system=JUDGE_SYSTEM,
                               think=False, temperature=0.0, max_tokens=4)
        return verdict.strip().lower().startswith('yes')


def summarize_qa(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    def mean(values):
        valid = [v for v in values if v is not None]
        return sum(valid) / len(valid) if valid else None

    by_type: dict[str, list[dict]] = {}
    for row in rows:
        by_type.setdefault(row['question_type'], []).append(row)
    type_acc = {task: mean([row['correct'] for row in group])
                for task, group in sorted(by_type.items())}
    abstention = [row for row in rows if row['question_id'].endswith('_abs')]
    values = [v for v in type_acc.values() if v is not None]
    return {
        'questions': len(rows),
        'accuracy': mean([row['correct'] for row in rows]),
        'task_averaged_accuracy': mean(values),
        'abstention_accuracy': mean([row['correct'] for row in abstention]) if abstention else None,
        'abstention_questions': len(abstention),
        'by_type': {task: {'questions': len(group), 'accuracy': type_acc[task]}
                    for task, group in sorted(by_type.items())},
    }


def run_qa(questions: Sequence[Question], retrieved_by_id: dict[str, Sequence],
           reader: Reader, judge: Judge, *, top_turns: int = 50,
           max_chars: int = 40000, progress=None,
           on_result=None) -> dict[str, Any]:
    rows = []
    for index, question in enumerate(questions, start=1):
        retrieved = retrieved_by_id.get(question.question_id, ())
        context = build_context(question, retrieved, top_turns=top_turns,
                                max_chars=max_chars)
        response = reader.answer(question.question, context,
                                 question_type=question.question_type)
        label = judge.correct(question, response)
        row = {
            'question_id': question.question_id,
            'question_type': question.question_type,
            'question': question.question,
            'answer': question.answer,
            'response': response,
            'correct': bool(label),
            'context_sessions': len({s.session_id for s, _, _ in
                                     _selected_turns(question, retrieved, top_turns)}),
        }
        rows.append(row)
        if on_result is not None:
            on_result(row)
        if progress is not None:
            progress(index, len(questions), question, row)
    return {'summary': summarize_qa(rows), 'per_question': rows}
