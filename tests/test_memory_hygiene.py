"""P2 记忆卫生回归 (F6-2/F6-3/F6-9)。

- 缓存有上限且 clear_cache 连 decider 一起清。
- _save 二次校验证据 id: 幻影/跨玩家被过滤; identity 的跨流证据保留。
"""

from __future__ import annotations



from game_agent import MemoryRecord, NPC
from game_agent.models.embeddings import HashEmbedder
from game_agent.memory.store import MemoryStore
from game_agent.cognition.reflection import ReflectionEngine
from game_agent.cognition.npc import NPC_CACHE_LIMIT
from game_agent.cognition.reacting import EVENT_VALUE_CACHE_LIMIT
from tests.test_persistence import _StubLLM, TRAITS


def test_npc_decision_cache_is_bounded_and_clears_decider():
    npc = NPC("T", dict(TRAITS), llm=_StubLLM(), embedder=HashEmbedder())
    npc.set_tier("full")
    for i in range(NPC_CACHE_LIMIT + 50):
        npc.react(f"event unique{i} alpha{i}", "P", float(i))
    assert len(npc._cache) <= NPC_CACHE_LIMIT
    assert len(npc.decider._value_cache) <= EVENT_VALUE_CACHE_LIMIT
    npc.clear_cache()
    assert npc._cache == {}
    assert npc.decider._value_cache == {}


def test_save_filters_phantom_and_cross_stream_evidence():
    store = MemoryStore(HashEmbedder())
    engine = ReflectionEngine(_StubLLM(), HashEmbedder())
    shared_id = store.add(MemoryRecord(content="共享观察", timestamp=0.0,
                                       type="observation", player_id=None))
    a_id = store.add(MemoryRecord(content="Aria 的观察", timestamp=1.0,
                                  type="observation", player_id="Aria"))
    rec_id = engine._save(store, 2.0, "共享反思", [shared_id, a_id, 9999],
                          None, 0.8, shared=True)
    rec = [m for m in store.all_valid(shared=True, types=["reflection"])
           if m.id == rec_id][0]
    assert rec.evidence == [shared_id], "跨玩家/幻影证据应被过滤"


def test_identity_evidence_keeps_cross_stream_reflection():
    store = MemoryStore(HashEmbedder())
    engine = ReflectionEngine(_StubLLM(), HashEmbedder())
    obs_id = store.add(MemoryRecord(content="共享观察", timestamp=0.0,
                                    type="observation", player_id=None))
    rel_id = store.add(MemoryRecord(content="Aria 值得信任", timestamp=1.0,
                                    type="reflection", player_id="Aria"))
    ident_id = engine._save(store, 2.0, "我倾向于信任来客",
                            [obs_id, rel_id], None, 0.8,
                            rtype="identity", shared=True,
                            cross_stream=True)
    ident = [m for m in store.all_valid(shared=True, types=["identity"])
             if m.id == ident_id][0]
    assert ident.evidence == [obs_id, rel_id]


def test_all_invalid_reads_new_columns_and_world_closes_npc_stores(tmp_path):
    import sqlite3
    import pytest
    from game_agent import Location, World

    store = MemoryStore(HashEmbedder())
    mid = store.add(MemoryRecord(content="失效反思", timestamp=0.0,
                                 type="reflection", player_id="Aria",
                                 hearsay=True, hop=2, confidence=0.4))
    store.invalidate(mid)
    rec = store.all_invalid()[0]
    assert rec.hearsay is True and rec.hop == 2
    assert rec.confidence == 0.4
    store.close()

    w = World("w", [Location("L", 0, 0)])
    w.add_npc("A", dict(TRAITS), llm=_StubLLM(),
              data_dir=str(tmp_path / "A"), location="L")
    npc = w.npc("A")
    w.close()
    with pytest.raises(sqlite3.ProgrammingError):
        npc.memory_count()


def test_merge_promotes_richer_content_and_invalidates_vector():
    store = MemoryStore(HashEmbedder())
    mid = store.add(MemoryRecord(content="P 在 L", timestamp=0.0,
                                 type="observation", player_id="P"))
    assert mid in store._vec_cache
    store.merge_observation(mid, now=1.0,
                            new_content="P 出现在 L, 靠近 NPC")
    assert store.all_valid()[0].content == "P 出现在 L, 靠近 NPC"
    assert mid not in store._vec_cache, "内容更新后必须清向量缓存"
    # 更短/等长不覆盖
    store.merge_observation(mid, now=2.0, new_content="P 在 L")
    assert store.all_valid()[0].content == "P 出现在 L, 靠近 NPC"
