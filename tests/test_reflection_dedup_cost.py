"""反思去重嵌入成本测试 (L1 回归)。

_save 去重改走 store 缓存向量: 已有反思的向量在 add 时已缓存, 去重比较零嵌入,
每次 _save 只嵌入新洞察一次 (O(1)), 不再把该玩家全部已有反思整批重嵌入 (O(n))。
用计数嵌入器断言: reflect_relationship 的嵌入调用数不随已有反思数增长。
无网络。
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from persona_agent import MemoryRecord, MemoryStore
from persona_agent.embeddings import Embedder, HashEmbedder
from persona_agent.reflection import ReflectionEngine
from tests.test_persistence import _StubLLM


class CountingEmbedder(Embedder):
    """包装真实 embedder, 计数 embed 调用次数 (每次调用 = 一次网络请求)。"""

    def __init__(self, inner: Embedder) -> None:
        self._inner = inner
        self.calls = 0

    @property
    def dim(self) -> int:
        return self._inner.dim

    def embed(self, texts):
        self.calls += 1
        return self._inner.embed(texts)


def test_save_dedup_uses_cached_vectors(tmp_path):
    """已有 10 条反思时, reflect_relationship 只多 2 次嵌入 (查询 + 新洞察),
    不是 3 次 (查询 + 整批重嵌入已有反思 + 新洞察)。嵌入数不随已有反思数增长。"""
    embedder = CountingEmbedder(HashEmbedder())
    store = MemoryStore(embedder)
    for i in range(10):   # 10 条已有反思, add 时各嵌入一次
        store.add(MemoryRecord(content=f"Aria 第{i}条独立认知", timestamp=float(i),
                               type="reflection", player_id="Aria", confidence=0.6))
    store.add(MemoryRecord(content="Aria 帮 Klaus 修了咖啡机", timestamp=10.0,
                           type="observation", player_id="Aria", importance=6.0))
    engine = ReflectionEngine(_StubLLM(), embedder)

    before = embedder.calls
    engine.reflect_relationship(store, "Aria", now=11.0)
    # retrieve 嵌入查询 (1) + _save 嵌入新洞察 (1, 判重用) + store.add 入库再嵌 (1)
    # = 3; 已有 10 条反思走 store 缓存 (0)。旧实现多一次整批重嵌入已有反思 = 4。
    assert embedder.calls == before + 3, \
        (f"应只多 3 次嵌入 (查询+新洞察×2), 实际多 {embedder.calls - before} 次 "
         "(旧实现: 再整批重嵌入 10 条已有反思 = 4 次)")

    # 再生成一次: 同 "stub-insight" 被去重跳过 (不 add), 但仍嵌入 2 次 (查询+判重), 不随已有反思数涨
    before2 = embedder.calls
    engine.reflect_relationship(store, "Aria", now=12.0)
    assert embedder.calls == before2 + 2, \
        f"去重命中不入库, 应只多 2 次嵌入, 实际多 {embedder.calls - before2} 次"
