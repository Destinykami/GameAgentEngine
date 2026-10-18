"""向量批量补 miss 回归 (F6-8)。"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from persona_agent import MemoryRecord
from persona_agent.embeddings import HashEmbedder
from persona_agent.memory import MemoryStore


class _CountingEmbedder(HashEmbedder):
    def __init__(self) -> None:
        super().__init__()
        self.batch_sizes = []

    def embed(self, texts):
        texts = list(texts)
        self.batch_sizes.append(len(texts))
        return super().embed(texts)


def test_retrieve_batches_cold_cache_misses():
    emb = _CountingEmbedder()
    store = MemoryStore(emb)
    for i in range(5):
        store.add(MemoryRecord(content=f"memory unique{i} alpha{i}",
                               timestamp=float(i), type="observation",
                               player_id="P"))
    emb.batch_sizes.clear()
    store._vec_cache.clear()   # 模拟冷启动
    store.retrieve("memory unique3 alpha3", now=10.0, player_id="P",
                   mark_accessed=False)
    assert 5 in emb.batch_sizes, f"候选应批量嵌入一次, 实际 {emb.batch_sizes}"
    store.close()


def test_vectors_helper_batches():
    emb = _CountingEmbedder()
    store = MemoryStore(emb)
    for i in range(4):
        store.add(MemoryRecord(content=f"v unique{i} beta{i}",
                               timestamp=float(i), type="observation"))
    recs = store.all_valid()
    emb.batch_sizes.clear()
    store._vec_cache.clear()
    vecs = store.vectors(recs)
    assert len(vecs) == 4
    assert emb.batch_sizes == [4]
    store.close()
