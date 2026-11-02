"""LongMemEval reader/LLM judge 的离线契约；不调用真实模型。"""
import json
from dataclasses import replace
from pathlib import Path

from evals.longmemeval.dataset import load_questions
from evals.longmemeval.qa import (LLMJudge, LLMReader, build_context, judge_prompt,
                                  run_qa, summarize_qa)

FIXTURE = Path(__file__).resolve().parents[1] / 'evals' / 'longmemeval' / 'fixtures' / 'sample.json'


class FakeReader:
    def __init__(self):
        self.calls = []

    def answer(self, question, context, *, question_type=''):
        self.calls.append((question, context, question_type))
        return 'Mochi'


class FakeJudge:
    def __init__(self, labels):
        self.labels = iter(labels)
        self.calls = []

    def correct(self, question, response):
        self.calls.append((question.question_id, response))
        return next(self.labels)


def test_reader_context_uses_retrieved_turns_and_dates():
    question = load_questions(FIXTURE)[0]
    one = build_context(question, [{'session_id': 's2', 'turn_index': 0}],
                        top_turns=1)
    assert 'session s2' in one
    assert '2023/04/03' in one
    assert 'Mochi' not in one
    both = build_context(question, [{'session_id': 's1', 'turn_index': 0},
                                    {'session_id': 's2', 'turn_index': 0}], top_turns=2)
    assert 'Mochi' in both and 'bicycle' in both


def test_run_qa_aggregates_accuracy_and_abstention():
    questions = list(load_questions(FIXTURE))
    retrieved = {q.question_id: [{'session_id': q.sessions[0].session_id,
                                      'turn_index': 0}] for q in questions}
    reader = FakeReader()
    judge = FakeJudge([True, False])
    result = run_qa(questions, retrieved, reader, judge, top_turns=2)
    assert result['summary']['questions'] == 2
    assert result['summary']['accuracy'] == 0.5
    assert result['summary']['task_averaged_accuracy'] == 0.5
    assert result['summary']['abstention_questions'] == 0
    assert result['per_question'][0]['context_sessions'] == 1


def test_judge_prompt_switches_by_question_type_and_abstention():
    question = load_questions(FIXTURE)[0]
    assert 'Correct Answer' in judge_prompt(question, 'Mochi')
    assert 'Rubric' in judge_prompt(replace(question, question_type='single-session-preference'), 'x')
    assert 'off-by-one' in judge_prompt(replace(question, question_type='temporal-reasoning'), 'x')
    assert 'unanswerable question' in judge_prompt(
        replace(question, question_id='q_abs'), 'x')


def test_llm_reader_and_judge_use_llm_ask_contract():
    class FakeLLM:
        def __init__(self):
            self.calls = []

        def ask(self, prompt, **options):
            self.calls.append((prompt, options))
            return 'Yes' if 'Is the model response correct' in prompt else '25:50'

    llm = FakeLLM()
    question = load_questions(FIXTURE)[0]
    reader = LLMReader(llm)
    judge = LLMJudge(llm)
    response = reader.answer(question.question, 'user: Mochi')
    assert response == '25:50'
    assert judge.correct(question, response) is True
    assert '历史' in llm.calls[0][0]
    assert 'Correct Answer' in llm.calls[1][0]
    assert llm.calls[0][1]['temperature'] == 0.0
    assert llm.calls[1][1]['max_tokens'] == 4


def test_qa_summary_task_average_and_abstention():
    rows = [
        {'question_id': 'a', 'question_type': 'single-session-user', 'correct': True},
        {'question_id': 'b', 'question_type': 'multi-session', 'correct': False},
        {'question_id': 'c_abs', 'question_type': 'single-session-user', 'correct': True},
    ]
    summary = summarize_qa(rows)
    assert summary['accuracy'] == 2 / 3
    assert summary['task_averaged_accuracy'] == 0.5
    assert summary['abstention_accuracy'] == 1.0
    assert summary['abstention_questions'] == 1
