"""LongMemEval 新模式复用生产检索，严格区分完整索引与降级结果。"""
import json
from pathlib import Path

import pytest

from evals.longmemeval.backend import GameAgentMemoryBackend
from evals.longmemeval.cli import main
from evals.longmemeval.dataset import Question, Session, Turn, load_questions
from evals.longmemeval.runner import evaluate
from game_agent import MemoryStore
from game_agent.memory import HybridResult
from tests.test_hybrid_retrieval import ToyEmbedder

FIXTURE = Path(__file__).resolve().parents[1] / 'evals/longmemeval/fixtures/sample.json'


@pytest.mark.parametrize('mode', ['bm25', 'dense', 'hybrid'])
def test_new_modes_use_core_interface_and_map_unique_turns(mode, monkeypatch):
    calls = []
    original = MemoryStore.hybrid_retrieve
    def spy(self, query, scope, **options):
        calls.append(options)
        return original(self, query, scope, **options)
    monkeypatch.setattr(MemoryStore, 'hybrid_retrieve', spy)
    question = load_questions(FIXTURE)[0]
    backend = GameAgentMemoryBackend(retrieval=mode)
    result = evaluate([question], backend, top_k=5, ks=(5,))
    assert calls == [{'top_k': 5, 'candidate_k': 32, 'mode': mode, 'index_limit': 0}]
    row = result['per_question'][0]
    assert len({(r['session_id'], r['turn_index']) for r in row['retrieved']}) == len(row['retrieved'])
    assert row['retrieval_diagnostics']['mode'] == mode
    assert not row['retrieval_diagnostics']['errors']
    if mode != 'bm25':
        assert row['retrieval_diagnostics']['dense_complete']
        assert row['retrieval_diagnostics']['indexed_chunks'] >= question.turn_count


def test_bm25_does_not_require_embedding_service():
    embedder = ToyEmbedder()
    embedder.fail = True
    backend = GameAgentMemoryBackend(embedder, retrieval='bm25')
    assert backend.retrieve(load_questions(FIXTURE)[0], 5)
    assert embedder.calls == []


@pytest.mark.parametrize('mode', ['dense', 'hybrid'])
def test_index_failure_cannot_be_reported_as_success(mode):
    embedder = ToyEmbedder()
    embedder.fail = True
    backend = GameAgentMemoryBackend(embedder, retrieval=mode)
    with pytest.raises(RuntimeError, match='索引失败'):
        backend.retrieve(load_questions(FIXTURE)[0], 5)
    assert backend.last_diagnostics == {}


def test_degraded_core_result_is_rejected_by_evaluation(monkeypatch):
    monkeypatch.setattr(MemoryStore, 'hybrid_retrieve', lambda *args, **kwargs:
        HybridResult((), {'dense_complete': False, 'errors': []}))
    with pytest.raises(RuntimeError, match='覆盖不完整'):
        GameAgentMemoryBackend(retrieval='hybrid').retrieve(load_questions(FIXTURE)[0], 5)


def test_no_progress_index_does_not_loop_forever(monkeypatch):
    monkeypatch.setattr(MemoryStore, 'index_archive', lambda *args, **kwargs:
        {'indexed': 0, 'remaining': 10, 'complete': False, 'errors': []})
    with pytest.raises(RuntimeError, match='未取得进展'):
        GameAgentMemoryBackend(retrieval='dense').retrieve(load_questions(FIXTURE)[0], 5)


def test_late_chunk_maps_to_original_turn_and_future_history_is_excluded():
    content = 'ordinary ' * 160 + 'feline evidence'
    question = Question('q', 'single-session-user', '猫咪', 'answer', 10,
        (Session('past', 1, (Turn('user', content, True),)),
         Session('future', 20, (Turn('user', 'feline future secret'),))), frozenset({'past'}))
    backend = GameAgentMemoryBackend(ToyEmbedder(), retrieval='hybrid')
    result = backend.retrieve(question, 5)
    assert len(result) == 1 and result[0].session_id == 'past'
    assert result[0].content == content  # 标准指标/旧 reader 的单位仍为完整 turn。
    match = backend.last_diagnostics['matches'][0]
    assert match['start'] > 0 and 'feline' in match['content']
    assert match['content'] == content[match['start']:match['end']]


@pytest.mark.parametrize('mode', ['bm25', 'dense', 'hybrid'])
def test_cli_modes_write_valid_results_diagnostics_and_summary(mode, tmp_path):
    out = tmp_path / mode
    args = ['--data', str(FIXTURE), '--retrieval', mode, '--limit', '2',
            '--top-k', '5', '--out', str(out)]
    assert main(args) == 0
    summary = json.loads((out / 'summary.json').read_text())
    rows = [json.loads(line) for line in (out / 'per_question.jsonl').read_text().splitlines()]
    assert summary['retrieval'] == mode and summary['questions'] == 2
    assert summary['retrieval_diagnostics']['degraded_questions'] == 0
    assert all(row['retrieval_diagnostics']['mode'] == mode for row in rows)
    assert main([*args, '--resume']) == 0
    with pytest.raises(SystemExit, match='模式'):
        main([*args, '--retrieval', 'memory', '--resume'])
    (out / 'summary.json').unlink()
    other = 'dense' if mode != 'dense' else 'hybrid'
    with pytest.raises(SystemExit, match='诊断'):
        main([*args, '--retrieval', other, '--resume'])
