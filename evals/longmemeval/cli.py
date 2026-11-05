"""LongMemEval 召回评测 CLI；真实数据路径显式传入，默认只读小 fixture。"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from evals.paths import run_dir
from game_agent.models.embeddings import HashEmbedder

from .backend import RETRIEVAL_MODES, GameAgentMemoryBackend
from .dataset import load_questions
from .metrics import DEFAULT_KS, summarize
from .qa import LLMJudge, LLMReader, run_qa, summarize_qa
from .runner import evaluate

HERE = Path(__file__).resolve().parent
FIXTURE = HERE / 'fixtures' / 'sample.json'


def _args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', default=str(FIXTURE),
                        help='LongMemEval JSON；默认内置 2 题 fixture')
    parser.add_argument('--limit', type=int, default=2,
                        help='最多评测题数；0 表示全部')
    parser.add_argument('--top-k', type=int, default=50,
                        help='每 retrieval 保留的 turn 数，至少为 5')
    parser.add_argument('--embedder', choices=('hash', 'real'), default='hash',
                        help='hash=离线确定性；real=make_embedder（可能回退）')
    parser.add_argument('--question-type', default=None,
                        help='只跑指定 question_type')
    parser.add_argument('--retrieval', choices=RETRIEVAL_MODES, default='memory',
                        help='旧排序 memory/relevance/session；原文核心对照 bm25/dense/hybrid')
    parser.add_argument('--sample', choices=('first', 'stratified'), default='first',
                        help='limit 截断方式；stratified 按 question_type 轮转，适合 smoke')
    parser.add_argument('--out', default=None,
                        help='产物目录；默认 data/eval/longmemeval/<时间戳>')
    parser.add_argument('--resume', action='store_true',
                        help='跳过 per_question.jsonl 中已完成的 question_id')
    parser.add_argument('--qa', action='store_true',
                        help='召回后运行 reader + LLM judge')
    parser.add_argument('--qa-results', default=None,
                        help='复用已有 per_question.jsonl，直接运行 QA')
    parser.add_argument('--qa-resume', action='store_true',
                        help='跳过 qa.jsonl 中已完成的 question_id')
    parser.add_argument('--qa-turns', type=int, default=50,
                        help='reader 使用的 top turn 数')
    parser.add_argument('--qa-max-chars', type=int, default=40000,
                        help='reader 历史字符预算')
    return parser.parse_args(argv)


def _embedder(kind: str):
    if kind == 'hash':
        return HashEmbedder()
    from game_agent.models.embeddings_http import make_embedder
    return make_embedder()


def _select(questions, limit: int, sample: str):
    if not limit or sample == 'first':
        return questions[:limit] if limit else questions
    buckets: dict[str, list] = {}
    for question in questions:
        buckets.setdefault(question.question_type, []).append(question)
    chosen = []
    while len(chosen) < limit and any(buckets.values()):
        for kind in sorted(buckets):
            if buckets[kind] and len(chosen) < limit:
                chosen.append(buckets[kind].pop(0))
    return chosen


def _load_jsonl(path: str) -> list[dict]:
    if not os.path.exists(path):
        return []
    with open(path, encoding='utf-8') as stream:
        return [json.loads(line) for line in stream if line.strip()]


def _print_qa(summary: dict) -> None:
    def fmt(value):
        return '-' if value is None else f'{value:.4f}'
    print(f"\nQA: questions={summary['questions']} "
          f"accuracy={fmt(summary['accuracy'])} "
          f"task_avg={fmt(summary['task_averaged_accuracy'])} "
          f"abstention={fmt(summary['abstention_accuracy'])} "
          f"(n={summary['abstention_questions']})")
    for task, group in summary['by_type'].items():
        print(f"  {task}: {fmt(group['accuracy'])} (n={group['questions']})")


def _run_qa(args, questions, retrieved_by_id, out: str, *, retrieval: str | None) -> int:
    os.makedirs(out, exist_ok=True)
    qa_path = os.path.join(out, 'qa.jsonl')
    existing = _load_jsonl(qa_path) if args.qa_resume else []
    done = {row['question_id'] for row in existing}
    questions = [q for q in questions if q.question_id in retrieved_by_id
                 and q.question_id not in done]
    from game_agent.models.llm_http import RealLLM
    llm = RealLLM()
    reader, judge = LLMReader(llm), LLMJudge(llm)
    with open(qa_path, 'a' if args.qa_resume else 'w', encoding='utf-8') as sink:
        def save(row):
            sink.write(json.dumps(row, ensure_ascii=False) + '\n')
            sink.flush()

        def progress(index, total, question, row):
            print(f'[qa {index}/{total}] {question.question_id} '
                  f'{question.question_type} correct={row["correct"]}',
                  file=sys.stderr, flush=True)

        result = run_qa(questions, retrieved_by_id, reader, judge,
                        top_turns=args.qa_turns, max_chars=args.qa_max_chars,
                        progress=progress, on_result=save)
    combined = existing + result['per_question']
    summary = {
        'data': str(Path(args.data).resolve()),
        'reader': type(llm).__name__,
        'judge': type(llm).__name__,
        'qa_turns': args.qa_turns,
        'qa_max_chars': args.qa_max_chars,
        'retrieval': retrieval,
        **summarize_qa(combined),
    }
    with open(os.path.join(out, 'qa_summary.json'), 'w', encoding='utf-8') as stream:
        json.dump(summary, stream, ensure_ascii=False, indent=2)
    _print_qa(summary)
    print(f'QA 产物: {os.path.abspath(out)}')
    return 0


def _print_section(label: str, data: dict, ks) -> None:
    print(f'\n{label}')
    for k in ks:
        parts = []
        for name in ('recall_all', 'recall_any', 'ndcg_any'):
            metric = data.get(f'{name}@{k}', {'mean': None, 'n': 0})
            value, count = metric['mean'], metric['n']
            text = '-' if value is None else f'{value:.3f}'
            parts.append(f'{name}@{k}={text} (n={count})')
        print('  ' + '  '.join(parts))


def main(argv=None) -> int:
    args = _args(argv)
    if args.limit < 0:
        raise SystemExit('--limit 不能为负')
    if args.top_k < 5:
        raise SystemExit('--top-k 至少为 5')
    if args.retrieval in ('bm25', 'dense', 'hybrid') and args.top_k > 128:
        raise SystemExit('原文检索对照的 --top-k 最多为 128')
    ks = tuple(k for k in DEFAULT_KS if k <= args.top_k) or (args.top_k,)
    questions = list(load_questions(args.data))
    if args.question_type:
        questions = [q for q in questions if q.question_type == args.question_type]
    questions = _select(questions, args.limit, args.sample)
    if not questions:
        raise SystemExit('没有可评测问题')
    if args.qa_results:
        rows = _load_jsonl(args.qa_results)
        by_id = {row['question_id']: row.get('retrieved', ()) for row in rows}
        questions = [q for q in questions if q.question_id in by_id]
        if not questions:
            raise SystemExit('qa-results 中没有匹配题目')
        out = args.out or run_dir('longmemeval-qa')
        return _run_qa(args, questions, by_id, out, retrieval=None)
    out = args.out or run_dir('longmemeval')
    os.makedirs(out, exist_ok=True)
    rows_path = os.path.join(out, 'per_question.jsonl')
    existing = []
    if args.resume and os.path.exists(rows_path):
        with open(rows_path, encoding='utf-8') as stream:
            existing = [json.loads(line) for line in stream if line.strip()]
        summary_path = os.path.join(out, 'summary.json')
        if os.path.exists(summary_path):
            with open(summary_path, encoding='utf-8') as stream:
                previous = json.load(stream)
            if previous.get('retrieval') != args.retrieval or previous.get('top_k') != args.top_k:
                raise SystemExit('resume 的检索模式或 top-k 与原结果不一致，请使用新的输出目录')
        for row in existing:
            mode = row.get('retrieval_diagnostics', {}).get('mode')
            if ((mode is not None and mode != args.retrieval)
                    or (args.retrieval in ('bm25', 'dense', 'hybrid') and mode is None)):
                raise SystemExit('resume 结果缺少相同检索模式的诊断，请使用新的输出目录')
    done = {row['question_id'] for row in existing}
    questions = [q for q in questions if q.question_id not in done]
    embedder = _embedder(args.embedder)
    backend = GameAgentMemoryBackend(embedder, retrieval=args.retrieval)

    def progress(index, total, question, row):
        print(f'[{index}/{total}] {question.question_id} {question.question_type} '
              f'turn_all@5={row["turn"]["recall_all@5"]}', file=sys.stderr, flush=True)

    with open(rows_path, 'a' if args.resume else 'w', encoding='utf-8') as sink:
        def save(row):
            sink.write(json.dumps(row, ensure_ascii=False) + '\n')
            sink.flush()

        result = evaluate(questions, backend, top_k=args.top_k, ks=ks,
                          progress=progress, on_result=save)
    combined = existing + result['per_question']
    summary = {
        'data': str(Path(args.data).resolve()),
        'embedder': type(embedder).__name__,
        'top_k': args.top_k,
        'retrieval': args.retrieval,
        'ks': list(ks),
        **summarize(combined, ks),
    }
    diagnostics = [row['retrieval_diagnostics'] for row in combined if 'retrieval_diagnostics' in row]
    if diagnostics:
        summary['retrieval_diagnostics'] = {
            'questions': len(diagnostics),
            'degraded_questions': sum(bool(d.get('errors')) or d.get('dense_complete') is False
                                      for d in diagnostics),
            'indexed_chunks': sum(d.get('indexed_chunks', 0) for d in diagnostics),
            'mean_indexing_ms': sum(d.get('indexing_ms', 0) for d in diagnostics)/len(diagnostics),
            'mean_retrieval_ms': sum(d['latency_ms'] for d in diagnostics)/len(diagnostics),
            'mean_pipeline_ms': sum(d.get('pipeline_ms', 0) for d in diagnostics)/len(diagnostics),
        }
    with open(os.path.join(out, 'summary.json'), 'w', encoding='utf-8') as stream:
        json.dump(summary, stream, ensure_ascii=False, indent=2, default=str)
    print(f'LongMemEval: {len(combined)} questions, embedder={type(embedder).__name__}, '
          f'top_k={args.top_k}, retrieval={args.retrieval}, ks={ks}')
    _print_section('Turn-level', summary['turn'], ks)
    _print_section('Session-level', summary['session'], ks)
    print('\nBy question_type')
    for question_type, group in summary['by_type'].items():
        print(f'  {question_type}: {group["questions"]} questions')
        _print_section('  turn', group['turn'], ks)
        _print_section('  session', group['session'], ks)
    print(f'\n产物: {os.path.abspath(out)}')
    if args.qa:
        by_id = {row['question_id']: row.get('retrieved', ())
                 for row in combined}
        return _run_qa(args, questions, by_id, out, retrieval=args.retrieval)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
