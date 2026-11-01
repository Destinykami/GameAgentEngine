"""LongMemEval 独立评测模块：数据、指标、后端和 CLI 的离线契约。"""
import json
from pathlib import Path
import subprocess
import sys

import pytest

from evals.longmemeval.backend import GameAgentMemoryBackend, _CachedBatchEmbedder
from evals.longmemeval.cli import main
from evals.longmemeval.dataset import (Question, RetrievedTurn, Session, Turn,
                                       load_questions, parse_time)
from evals.longmemeval.metrics import evaluate_question
from game_agent.models.embeddings import HashEmbedder

FIXTURE = Path(__file__).resolve().parents[1] / 'evals' / 'longmemeval' / 'fixtures' / 'sample.json'


def test_fixture_loads_with_dates_and_turn_evidence():
    questions = load_questions(FIXTURE)
    assert len(questions) == 2
    first = questions[0]
    assert first.question_id == 'sample-single-user'
    assert first.answer == 'Mochi'
    assert first.answer_session_ids == {'s1'}
    assert len(first.sessions) == 2
    assert first.evidence_turns() == {'s1#0'}
    assert first.at > first.sessions[0].at
    assert parse_time('2023/04/01 (Sat) 10:00') == first.sessions[0].at
    with pytest.raises(ValueError):
        parse_time('not-a-date')


def _question():
    return Question(
        question_id='q', question_type='single-session-user', question='dog?',
        answer='Mochi', at=10.0,
        sessions=(
            Session('s1', 1.0, (Turn('user', 'Mochi', True), Turn('assistant', 'ok'))),
            Session('s2', 2.0, (Turn('user', 'bicycle'),)),
        ),
        answer_session_ids=frozenset({'s1'}),
    )


def _turn(session, index, has_answer=False):
    return RetrievedTurn(session, index, 'user', 'x', has_answer, 1.0, 0.5)


def test_turn_and_session_metrics_follow_binary_recall_and_ndcg():
    q = _question()
    wrong_then_right = [_turn('s2', 0), _turn('s1', 0, True)]
    metrics = evaluate_question(q, wrong_then_right, ks=(1, 2))
    assert metrics['turn']['recall_all@1'] == 0.0
    assert metrics['turn']['recall_all@2'] == 1.0
    assert metrics['turn']['recall_any@2'] == 1.0
    assert metrics['turn']['ndcg_any@1'] == 0.0
    assert metrics['turn']['ndcg_any@2'] == 1.0
    assert metrics['session']['recall_all@1'] == 0.0
    assert metrics['session']['recall_all@2'] == 1.0
    assert metrics['session']['ndcg_any@2'] == 1.0


def test_multi_document_recall_requires_all_evidence():
    q = _question()
    q = Question(q.question_id, q.question_type, q.question, q.answer, q.at,
                 q.sessions, frozenset({'s1', 's2'}))
    # session 级证据两段，只召回一段：recall_all=0，NDCG 为部分增益。
    metrics = evaluate_question(q, [_turn('s1', 0, True)], ks=(5,))
    assert metrics['session']['recall_all@5'] == 0.0
    assert metrics['session']['recall_any@5'] == 1.0
    assert 0.0 < metrics['session']['ndcg_any@5'] < 1.0


def test_memory_backend_maps_retrieved_turns_back_to_sessions():
    question = load_questions(FIXTURE)[0]
    retrieved = GameAgentMemoryBackend().retrieve(question, top_k=50)
    assert len(retrieved) == question.turn_count
    assert {turn.session_id for turn in retrieved} == {'s1', 's2'}
    assert all(turn.turn_key.startswith(turn.session_id + '#') for turn in retrieved)
    assert all(turn.score >= 0.0 for turn in retrieved)


def test_cli_smoke_writes_summary_and_per_question(tmp_path):
    out = tmp_path / 'run'
    assert main(['--data', str(FIXTURE), '--limit', '2', '--top-k', '5',
                 '--out', str(out)]) == 0
    summary = json.loads((out / 'summary.json').read_text(encoding='utf-8'))
    lines = [json.loads(line) for line in
             (out / 'per_question.jsonl').read_text(encoding='utf-8').splitlines()]
    assert summary['questions'] == 2
    assert summary['embedder'] == 'HashEmbedder'
    assert summary['ks'] == [5]
    assert len(lines) == 2
    assert all(row['question_id'] for row in lines)
    assert summary['turn']['recall_all@5']['n'] == 2


def test_cli_stratified_sampling_covers_question_types(tmp_path):
    out = tmp_path / 'stratified'
    assert main(['--data', str(FIXTURE), '--limit', '2', '--top-k', '5',
                 '--sample', 'stratified', '--out', str(out)]) == 0
    rows = [json.loads(line) for line in
            (out / 'per_question.jsonl').read_text(encoding='utf-8').splitlines()]
    assert {row['question_type'] for row in rows} == {'single-session-user', 'multi-session'}


def test_dataset_and_metrics_import_without_engine():
    root = Path(__file__).resolve().parents[1]
    code = ("import sys; import evals.longmemeval.dataset; "
            "import evals.longmemeval.metrics; "
            "assert 'game_agent' not in sys.modules")
    subprocess.run([sys.executable, '-c', code], cwd=root, check=True)


def test_backend_precomputes_turn_embeddings_in_batches():
    class CountingEmbedder(HashEmbedder):
        def __init__(self):
            super().__init__()
            self.calls = []

        def embed(self, texts):
            self.calls.append(len(texts))
            return super().embed(texts)

    question = load_questions(FIXTURE)[0]
    embedder = CountingEmbedder()
    backend = GameAgentMemoryBackend(embedder, batch_size=2)
    backend.retrieve(question, top_k=5)
    assert embedder.calls == [2, 2, 1]  # 4 个 turn 两批 + 查询一次


def test_cached_embedder_clips_and_splits_rejected_batches():
    class FlakyEmbedder(HashEmbedder):
        def __init__(self):
            super().__init__()
            self.calls = []
            self.max_input = 0

        def embed(self, texts):
            self.calls.append(len(texts))
            self.max_input = max(self.max_input, *(len(t) for t in texts))
            if len(texts) > 1:
                raise RuntimeError('batch too large')
            return super().embed(texts)

    embedder = FlakyEmbedder()
    cached = _CachedBatchEmbedder(embedder, ['x' * 10000, 'short'], batch_size=4)
    assert embedder.max_input <= 6000
    assert cached.embed(['x' * 10000])[0]
    assert cached.embed(['short'])[0]
    assert embedder.calls[0] == 2  # 先尝试整批，失败后二分


def test_backend_retrieval_modes_keep_ranking_contract():
    question = load_questions(FIXTURE)[0]
    for mode in ('memory', 'relevance', 'session'):
        turns = GameAgentMemoryBackend(retrieval=mode).retrieve(question, top_k=3)
        assert len(turns) == 3
        assert all(turn.score >= 0.0 for turn in turns)
    relevance = GameAgentMemoryBackend(retrieval='relevance').retrieve(question, 5)
    assert [turn.score for turn in relevance] == sorted(
        [turn.score for turn in relevance], reverse=True)
    session = GameAgentMemoryBackend(retrieval='session').retrieve(question, 5)
    ids = [turn.session_id for turn in session]
    assert ids == sorted(ids, key=lambda sid: ids.index(sid))


def test_cli_resume_skips_completed_questions(tmp_path):
    out = tmp_path / 'resume'
    args = ['--data', str(FIXTURE), '--top-k', '5', '--out', str(out)]
    assert main([*args, '--limit', '1']) == 0
    assert main([*args, '--limit', '2', '--resume']) == 0
    rows = [json.loads(line) for line in
            (out / 'per_question.jsonl').read_text(encoding='utf-8').splitlines()]
    assert len(rows) == 2
    assert len({row['question_id'] for row in rows}) == 2
    summary = json.loads((out / 'summary.json').read_text(encoding='utf-8'))
    assert summary['questions'] == 2


def test_cached_embedder_shortens_single_text_when_endpoint_rejects():
    class ShortLimitEmbedder(HashEmbedder):
        def __init__(self):
            super().__init__()
            self.last_input = 0

        def embed(self, texts):
            self.last_input = len(texts[0])
            if any(len(t) > 100 for t in texts):
                raise RuntimeError('input too long')
            return super().embed(texts)

    embedder = ShortLimitEmbedder()
    text = 'word ' * 2000
    cached = _CachedBatchEmbedder(embedder, [text])
    assert cached.embed([text])[0]
    assert embedder.last_input <= 100
