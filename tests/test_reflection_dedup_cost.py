"""反思去重嵌入成本测试 (L1 回归)。

_save 去重改走 store 缓存向量: 已有反思的向量在 add 时已缓存, 去重比较零嵌入,
每次 _save 只嵌入新洞察一次 (O(1)), 不再把该玩家全部已有反思整批重嵌入 (O(n))。
用计数嵌入器断言: reflect_relationship 的嵌入调用数不随已有反思数增长。
无网络。
"""

from __future__ import annotations


import pytest


from game_agent import MemoryRecord, MemoryStore
from game_agent.models.embeddings import Embedder, HashEmbedder
from game_agent.cognition.reflection import ReflectionEngine
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


class FixedVectorEmbedder(Embedder):
    """按内容返回预设单位向量, 精确控制余弦相似度 (HashEmbedder 无法卡阈值边界)。"""

    def __init__(self, vectors: dict[str, list[float]]) -> None:
        self._vectors = vectors
        self._dim = len(next(iter(vectors.values())))

    @property
    def dim(self) -> int:
        return self._dim

    def embed(self, texts):
        return [self._vectors[t] for t in texts]


def _unit_at(cosine: float) -> list[float]:
    """与 [1,0] 余弦为 cosine 的单位向量 [cosine, sqrt(1-cosine^2)]。"""
    return [cosine, (1.0 - cosine * cosine) ** 0.5]


def test_dedup_threshold_boundary_0_92(tmp_path):
    """E6: 去重阈值 0.92 —— 相似度 0.93 的同义复述被去重 (旧阈值 0.95 会放行入库),
    相似度 0.90 的独立洞察保留 (不过度去重)。用预设向量精确卡阈值两侧。"""
    base = [1.0, 0.0]
    emb = FixedVectorEmbedder({
        "认知 A": base,
        "认知 B (0.93 近重复)": _unit_at(0.93),
        "认知 C (0.90 独立)": _unit_at(0.90),
    })
    store = MemoryStore(emb)
    store.add(MemoryRecord(content="认知 A", timestamp=0.0, type="reflection",
                           player_id="Aria", confidence=0.6))
    engine = ReflectionEngine(_StubLLM(), emb)   # 默认 DEDUP_THRESHOLD=0.92

    # 0.93 >= 0.92 → 去重 (旧 0.95 阈值下 0.93 会入库, 这正是 E6 的失效场景)
    dup_id = engine._save(store, now=1.0, content="认知 B (0.93 近重复)",
                          evidence=[], player_id="Aria", confidence=0.6)
    assert dup_id is None, "相似度 0.93 >= 0.92 应去重 (旧阈值 0.95 会放行)"

    # 0.90 < 0.92 → 保留 (独立洞察, 不过度去重)
    keep_id = engine._save(store, now=2.0, content="认知 C (0.90 独立)",
                           evidence=[], player_id="Aria", confidence=0.6)
    assert keep_id is not None, "相似度 0.90 < 0.92 应保留 (独立洞察)"
