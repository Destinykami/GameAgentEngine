"""LongMemEval 召回评测 CLI；真实数据路径显式传入，默认只读小 fixture。"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from evals.paths import run_dir
from game_agent.models.embeddings import HashEmbedder

from .backend import GameAgentMemoryBackend
from .dataset import load_questions
from .metrics import DEFAULT_KS
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
    parser.add_argument('--sample', choices=('first', 'stratified'), default='first',
                        help='limit 截断方式；stratified 按 question_type 轮转，适合 smoke')
    parser.add_argument('--out', default=None,
                        help='产物目录；默认 data/eval/longmemeval/<时间戳>')
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
    ks = tuple(k for k in DEFAULT_KS if k <= args.top_k) or (args.top_k,)
    questions = list(load_questions(args.data))
    if args.question_type:
        questions = [q for q in questions if q.question_type == args.question_type]
    questions = _select(questions, args.limit, args.sample)
    if not questions:
        raise SystemExit('没有可评测问题')
    embedder = _embedder(args.embedder)
    backend = GameAgentMemoryBackend(embedder)
    result = evaluate(questions, backend, top_k=args.top_k, ks=ks)
    out = args.out or run_dir('longmemeval')
    os.makedirs(out, exist_ok=True)
    summary = {
        'data': str(Path(args.data).resolve()),
        'embedder': type(embedder).__name__,
        'top_k': args.top_k,
        'ks': list(ks),
        **result['summary'],
    }
    with open(os.path.join(out, 'summary.json'), 'w', encoding='utf-8') as stream:
        json.dump(summary, stream, ensure_ascii=False, indent=2, default=str)
    with open(os.path.join(out, 'per_question.jsonl'), 'w', encoding='utf-8') as stream:
        for row in result['per_question']:
            stream.write(json.dumps(row, ensure_ascii=False) + '\n')
    print(f'LongMemEval: {len(questions)} questions, embedder={type(embedder).__name__}, '
          f'top_k={args.top_k}, ks={ks}')
    _print_section('Turn-level', summary['turn'], ks)
    _print_section('Session-level', summary['session'], ks)
    print('\nBy question_type')
    for question_type, group in summary['by_type'].items():
        print(f'  {question_type}: {group["questions"]} questions')
        _print_section('  turn', group['turn'], ks)
        _print_section('  session', group['session'], ks)
    print(f'\n产物: {os.path.abspath(out)}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
