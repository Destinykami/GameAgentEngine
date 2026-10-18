"""记忆显著性与合并限速回归 (F2-1 / F2-2)。

- 同一观察在 6h 内重复只刷新 last_accessed, 不抬 importance; 时间窗外才 +1。
- 世界层每步 perceive 同一在场者不会把 importance 顶满 10。
- 去重前置: 重复观察不再消耗 score_importance 调用。
"""

from __future__ import annotations

import os
import sqlite3
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from persona_agent import Location, MemoryStore, NPC, World
from persona_agent.embeddings import HashEmbedder
from tests.test_persistence import _StubLLM, TRAITS

from persona_agent.memory import MERGE_REINFORCE_INTERVAL


class _CountingLLM(_StubLLM):
    def __init__(self) -> None:
        super().__init__()
        self.importance_calls = 0

    def score_importance(self, text, player_id=None):
        self.importance_calls += 1
        return super().score_importance(text, player_id)


def _npc(llm=None) -> NPC:
    return NPC("测试人", dict(TRAITS), llm=llm or _StubLLM(),
               embedder=HashEmbedder())


def test_merge_within_window_only_refreshes_access():
    npc = _npc()
    mid = npc.observe("Aria 帮过我", 0.0, player_id="Aria")
    npc.store.merge_observation(mid, now=1.0)
    rec = npc.store.all_valid(player_id="Aria")[0]
    assert rec.importance == 5.0, "6h 内重复只刷新 recency, 不抬 importance"
    assert rec.last_accessed == 1.0
    assert rec.base_importance == 5.0


def test_merge_after_window_reinforces_once():
    npc = _npc()
    mid = npc.observe("Aria 帮过我", 0.0, player_id="Aria")
    npc.store.merge_observation(mid, now=MERGE_REINFORCE_INTERVAL)
    rec = npc.store.all_valid(player_id="Aria")[0]
    assert rec.importance == 6.0, "时间窗外重复 +1"
    npc.store.merge_observation(mid, now=MERGE_REINFORCE_INTERVAL + 1.0)
    rec = npc.store.all_valid(player_id="Aria")[0]
    assert rec.importance == 6.0, "同一窗口内再次重复不叠加"


def test_repeated_presence_does_not_saturate_importance(tmp_path):
    w = World("w", [Location("L", 0, 0)])
    w.add_npc("A", dict(TRAITS), llm=_StubLLM(),
              data_dir=str(tmp_path / "A"), location="L")
    w.add_player("P", "L")
    w.schedule_tiers(0.0)
    for h in range(1, 13):
        w.perceive("A", float(h))
    obs = w.npc("A").store.all_valid(player_id="P", types=["observation"])
    assert len(obs) == 1
    assert obs[0].importance < 9.0, \
        f"12 步在场不得把 importance 顶到 10 (实际 {obs[0].importance})"
    w.close()


def test_duplicate_observation_skips_importance_llm():
    counting = _CountingLLM()
    npc = _npc(counting)
    npc.observe("Aria 帮过我", 0.0, player_id="Aria")
    assert counting.importance_calls == 1
    npc.observe("Aria 帮过我", 1.0, player_id="Aria")
    assert counting.importance_calls == 1, "重复观察应先去重, 零 LLM 增量"
    npc.observe("Aria 又帮了我一次", 2.0, player_id="Aria")
    assert counting.importance_calls == 2, "新观察照常打分"


def test_old_schema_migrates_last_reinforced(tmp_path):
    """F2-1 旧库迁移: 没有 last_reinforced 列时按 last_accessed/timestamp 补齐。"""
    path = str(tmp_path / "old.db")
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE memory ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, type TEXT NOT NULL,"
        "content TEXT NOT NULL, timestamp REAL NOT NULL,"
        "importance REAL NOT NULL DEFAULT 5.0, player_id TEXT,"
        "evidence TEXT DEFAULT '[]', confidence REAL DEFAULT 1.0,"
        "valid INTEGER DEFAULT 1, last_accessed REAL)")
    conn.execute(
        "INSERT INTO memory (type, content, timestamp, importance, player_id,"
        " last_accessed) VALUES ('observation', '旧观察', 0.0, 5.0, 'Aria', 5.0)")
    conn.commit()
    conn.close()

    store = MemoryStore(HashEmbedder(), path=path)
    rec = store.all_valid()[0]
    assert rec.last_reinforced == 5.0
    assert rec.base_importance == 5.0
    store.merge_observation(rec.id, now=11.0)   # 距锚点 6h → 强化一次
    assert store.all_valid()[0].importance == 6.0
    store.close()
