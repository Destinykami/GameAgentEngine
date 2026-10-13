"""关系反思兜底问题测试 (M1 回归): 兜底用本 NPC 真名, 不外泄 demo 名 "Klaus";
空白问题 ([""]) 触发兜底而非流进检索。

无网络, stub LLM。用 MemoryStore 子类捕获 retrieve 收到的查询来观察兜底问题。
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from persona_agent import MemoryRecord, MemoryStore
from persona_agent.embeddings import HashEmbedder
from persona_agent.reflection import ReflectionEngine
from tests.test_persistence import _StubLLM


class QueryCapturingStore(MemoryStore):
    """记录 retrieve 收到的查询, 用于观察兜底问题长什么样。"""

    def __init__(self, embedder) -> None:
        super().__init__(embedder)
        self.queries: list[str] = []

    def retrieve(self, query, now, **kw):
        self.queries.append(query)
        return super().retrieve(query, now, **kw)


class FallbackStubLLM(_StubLLM):
    """reflection_questions 按构造返回固定值; 不产生洞察 (embedder 不被用到)。"""

    def __init__(self, questions: list[str]) -> None:
        super().__init__()
        self._questions = questions

    def reflection_questions(self, recent):
        return list(self._questions)

    def reflection_insights(self, evidence, n: int = 5):
        return []


def _store_with_player() -> QueryCapturingStore:
    store = QueryCapturingStore(HashEmbedder())
    store.add(MemoryRecord(content="Bram 来过店里", timestamp=1.0,
                           type="observation", player_id="Bram", importance=6.0))
    return store


def test_fallback_uses_real_npc_name():
    """有名引擎: 问题生成空 → 兜底用本 NPC 真名。"""
    store = _store_with_player()
    engine = ReflectionEngine(FallbackStubLLM([]), None, npc_name="桃音")
    engine.reflect_relationship(store, "Bram", now=2.0)
    assert store.queries, "兜底问题应驱动一次证据检索"
    assert store.queries[-1] == "桃音 和 Bram 的关系如何?"
    assert "Klaus" not in " ".join(store.queries)


def test_fallback_neutral_when_no_name():
    """无名引擎 (直构造/测试): 兜底退中性 'NPC', 绝不外泄 demo 名。"""
    store = _store_with_player()
    engine = ReflectionEngine(FallbackStubLLM([]))   # 无 npc_name
    engine.reflect_relationship(store, "Bram", now=2.0)
    assert store.queries[-1] == "NPC 和 Bram 的关系如何?"
    assert "Klaus" not in " ".join(store.queries), "不得出现 demo 名字"


def test_blank_questions_trigger_fallback():
    """[''] 假问题: 被过滤, 触发兜底, 空字符串不得流入检索。"""
    store = _store_with_player()
    engine = ReflectionEngine(FallbackStubLLM([""]), None, npc_name="桃音")
    engine.reflect_relationship(store, "Bram", now=2.0)
    assert store.queries, "过滤空白后仍应有兜底检索"
    assert "" not in store.queries and None not in store.queries
    assert store.queries[-1] == "桃音 和 Bram 的关系如何?"


def test_normal_question_not_fallback():
    """正常问题不走兜底 (过滤不得误伤非空问题)。"""
    store = _store_with_player()
    engine = ReflectionEngine(FallbackStubLLM(["Bram 是不是常来店里?"]),
                              None, npc_name="桃音")
    engine.reflect_relationship(store, "Bram", now=2.0)
    assert store.queries[-1] == "Bram 是不是常来店里?"
    assert not any("的关系如何?" in q for q in store.queries)


def test_reflect_self_blank_question_filtered(tmp_path):
    """L9: 自我反思拿到 [''] 假问题时过滤掉, 空查询不流入证据检索, 静默跳过
    (无兜底 —— 与关系反思的保面兜底不对称是有意设计)。"""
    from persona_agent import MemoryRecord
    store = QueryCapturingStore(HashEmbedder())
    store.add(MemoryRecord(content="Klaus 把咖啡豆撒了一地", timestamp=0.0,
                           type="observation", importance=5.0))
    engine = ReflectionEngine(FallbackStubLLM([""]), None)
    result = engine.reflect_self(store, now=1.0)
    assert result == [], "空白问题过滤后无问题可问, 静默跳过"
    assert store.queries == [], "空查询不得流入证据检索 (零向量)"
