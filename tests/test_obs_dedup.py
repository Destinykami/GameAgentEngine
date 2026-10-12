"""观察层去重测试 (无网络, stub LLM + HashEmbedder)。"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from persona_agent import NPC, MemoryRecord
from tests.test_persistence import _StubLLM, TRAITS


def _make(tmp_path) -> NPC:
    return NPC.create("Fade", dict(TRAITS), llm=_StubLLM(), data_dir=str(tmp_path))


def test_identical_observation_merged(tmp_path):
    """同文观察重放 → 合并不新增, importance 提升, last_accessed 刷新。"""
    npc = _make(tmp_path)
    id1 = npc.observe("Aria 帮 Fade 修好了咖啡机", 0.0, player_id="Aria")
    id2 = npc.observe("Aria 帮 Fade 修好了咖啡机", 5.0, player_id="Aria")
    obs = npc.store.all_valid(player_id="Aria", types=["observation"])
    assert len(obs) == 1, "重复观察应合并, 不新增"
    assert id1 == id2
    assert obs[0].importance > 5.0, "合并应提升 importance"
    assert obs[0].last_accessed == 5.0, "合并应刷新 last_accessed"


def test_distinct_observations_kept(tmp_path):
    """不同事件不该被合并。"""
    npc = _make(tmp_path)
    npc.observe("Aria 帮 Fade 修好了咖啡机", 0.0, player_id="Aria")
    npc.observe("Aria 送了一束花给 Fade", 1.0, player_id="Aria")
    obs = npc.store.all_valid(player_id="Aria", types=["observation"])
    assert len(obs) == 2, "不同事件应各自入库"


def test_cross_player_not_merged(tmp_path):
    """相似文本属于不同玩家 → 不同关系流, 不合并。"""
    npc = _make(tmp_path)
    npc.observe("Aria 帮 Fade 修好了咖啡机", 0.0, player_id="Aria")
    npc.observe("Aria 帮 Fade 修好了咖啡机", 1.0, player_id="Bram")
    assert npc.store.count("Aria") == 1
    assert npc.store.count("Bram") == 1
    assert npc.memory_count() == 2


def test_merge_prevents_trust_inflation(tmp_path):
    """重复帮助不再重复计分: 1 次帮助 vs 1 次背叛 → 信任 0, 而非被灌水。"""
    npc = _make(tmp_path)
    npc.observe("Aria 帮 Fade 修好了咖啡机", 0.0, player_id="Aria")
    npc.observe("Aria 帮 Fade 修好了咖啡机", 1.0, player_id="Aria")  # 重放
    npc.observe("Bram 骗了 Fade, 拿走了他的咖啡豆", 2.0, player_id="Bram")
    # Aria: 合并后仅 1 条帮助 → +1.0 (若未合并, 2 条帮助仍 +1.0, 但条数不虚增)
    assert npc.store.count("Aria") == 1
    assert npc.trust_toward("Aria") == pytest.approx(1.0)
    assert npc.trust_toward("Bram") == pytest.approx(-1.0)


def test_merged_observation_resists_forgetting(tmp_path):
    """合并刷新的 last_accessed 让重复发生过的观察抗遗忘 (无需反思引用)。"""
    npc = _make(tmp_path)
    npc.observe("Fade 擦拭了店里的桌子", 0.0)
    npc.observe("Fade 擦拭了店里的桌子", 10.0)   # 合并, last_accessed=10
    # 40 天后: 未合并的观察 (age=40, 0.5*0.5^(40/48)=0.28) 仍存活;
    # 关键断言 —— 若反复重放到更久, 每次合并都刷新 last_accessed 延缓衰减
    npc.observe("Fade 擦拭了店里的桌子", 60.0)    # 再合并, last_accessed=60
    npc.forget(now=100.0)                          # age=40 (从 60 起算)
    obs = npc.store.all_valid(player_id=None, types=["observation"])
    assert len(obs) == 1 and obs[0].last_accessed == 60.0
    assert obs[0].valid, "被反复发生强化的观察不应被遗忘"


def test_reflection_evidence_survives_merge(tmp_path):
    """反思引用的观察 id 在合并后依然有效 (合并不改 id)。"""
    npc = _make(tmp_path)
    oid = npc.observe("Aria 帮 Fade 修好了咖啡机", 0.0, player_id="Aria")
    npc.store.add(MemoryRecord(content="Aria 值得信赖", timestamp=1.0,
                               type="reflection", player_id="Aria",
                               evidence=[oid], confidence=0.8))
    npc.observe("Aria 帮 Fade 修好了咖啡机", 2.0, player_id="Aria")  # 合并
    refs = npc.store.all_valid(player_id="Aria", types=["reflection"])
    assert refs and refs[0].evidence == [oid], "合并不应破坏反思证据链"
