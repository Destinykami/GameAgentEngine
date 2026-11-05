"""混合检索结果与排名融合；无数据库、模型或运行器依赖。"""
from __future__ import annotations
from dataclasses import dataclass


@dataclass(frozen=True)
class HybridResult:
    hits: tuple[dict, ...]
    diagnostics: dict
    neighbors: tuple[dict, ...] = ()


def fuse_rankings(routes: dict[str, list[dict]], *, constant: int = 60) -> list[dict]:
    """每一路每个原文来源只投一次票，返回稳定 RRF 排序。"""
    combined = {}
    for route, candidates in routes.items():
        seen = set()
        rank = 0
        for candidate in candidates:
            key = candidate['source_id']
            if key in seen:
                continue
            seen.add(key)
            rank += 1
            if key not in combined:
                combined[key] = dict(candidate, score=0.0, ranks={}, _best_rank=rank)
            item = combined[key]
            if rank < item['_best_rank']:
                for field in ('chunk_id', 'start', 'end'):
                    item[field] = candidate[field]
                item['_best_rank'] = rank
            item['score'] += 1.0 / (constant + rank)
            item['ranks'][route] = rank
            if candidate.get('hint_ids'):
                item['hint_ids'] = sorted(set(item.get('hint_ids', ())) | set(candidate['hint_ids']))
    result = sorted(combined.values(), key=lambda c: (-c['score'], -c['sequence'], c['start']))
    for item in result:
        item.pop('_best_rank')
    return result
