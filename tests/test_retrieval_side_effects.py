"""检索副作用与相关性下限测试 (M7 回归)。

Part A: retrieve 的 mark_accessed 开关 —— 反思证据检索 (候选) 不刷新遗忘锚点,
    对话式检索 (真回忆) 刷新。反思 10×3 问不再静默给 top_k 里没被引用的观察续命。
Part B: min_relevance 下限 —— 归一化前剔除零重叠无关候选, 小存储不再必返回满
    top_k 含无关记忆。
无网络, HashEmbedder。
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from persona_agent import MemoryRecord, MemoryStore
from persona_agent.embeddings import HashEmbedder
from persona_agent.reflection import ReflectionEngine
from tests.test_persistence import _StubLLM


def _store_with_obs(content: str, player_id: str | None) -> MemoryStore:
    store = MemoryStore(HashEmbedder())
    store.add(MemoryRecord(content=content, timestamp=0.0,
                           type="observation", player_id=player_id,
                           importance=5.0))
    return store


def test_reflect_relationship_evidence_does_not_refresh_anchor(tmp_path):
    """关系反思的证据检索 (mark_accessed=False) 不刷新 last_accessed ——
    候选 ≠ 回忆。走生产路径: ReflectionEngine.reflect_relationship。"""
    store = _store_with_obs("Aria 帮 Klaus 修了咖啡机", "Aria")
    engine = ReflectionEngine(_StubLLM(), HashEmbedder())
    engine.reflect_relationship(store, "Aria", now=100.0)
    obs = store.all_valid(player_id="Aria", types=["observation"])[0]
    assert obs.last_accessed is None, \
        "反思证据检索不应刷新遗忘锚点 (旧实现: 进 top_k 即刷新 → 100.0)"


def test_reflect_self_evidence_does_not_refresh_anchor(tmp_path):
    """自我反思的证据检索同样不刷新 last_accessed。"""
    store = _store_with_obs("Klaus 把咖啡豆撒了一地", None)
    engine = ReflectionEngine(_StubLLM(), HashEmbedder())
    engine.reflect_self(store, now=100.0)
    obs = store.all_valid(player_id=None, types=["observation"])[0]
    assert obs.last_accessed is None, "自我反思证据检索不应刷新遗忘锚点"


def test_dialogue_style_retrieve_refreshes_anchor(tmp_path):
    """对话式检索 (mark_accessed 默认 True) 刷新 last_accessed —— 真回忆。"""
    store = _store_with_obs("Aria 帮 Klaus 修了咖啡机", "Aria")
    store.retrieve(query="咖啡机", now=100.0, player_id="Aria")
    obs = store.all_valid(player_id="Aria", types=["observation"])[0]
    assert obs.last_accessed == pytest.approx(100.0), \
        "对话检索 (真回忆) 应刷新遗忘锚点"


def test_min_relevance_filters_irrelevant(tmp_path):
    """min_relevance 剔除与查询零词面重叠的记忆, 保留有重叠的 (归一化前)。"""
    store = MemoryStore(HashEmbedder())
    related = store.add(MemoryRecord(content="咖啡馆的咖啡豆到了",
                                     timestamp=0.0, type="observation",
                                     importance=5.0))
    unrelated = store.add(MemoryRecord(content="月亮很亮很圆",
                                       timestamp=0.0, type="observation",
                                       importance=5.0))
    res = store.retrieve(query="咖啡豆", now=1.0, min_relevance=0.1)
    ids = {m["id"] for m in res}
    assert related in ids, "与查询有词面重叠的记忆应保留"
    assert unrelated not in ids, "零重叠的记忆应被相关性下限剔除"


def test_min_relevance_zero_keeps_all(tmp_path):
    """min_relevance=0 (默认) 不过滤 —— 行为与旧版一致 (向后兼容)。"""
    store = MemoryStore(HashEmbedder())
    store.add(MemoryRecord(content="咖啡馆的咖啡豆到了", timestamp=0.0,
                           type="observation", importance=5.0))
    store.add(MemoryRecord(content="月亮很亮很圆", timestamp=0.0,
                           type="observation", importance=5.0))
    res = store.retrieve(query="咖啡豆", now=1.0)   # 默认 min_relevance=0
    assert len(res) == 2, "默认不过滤, 两条都返回"
