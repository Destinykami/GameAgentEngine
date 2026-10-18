"""NPC.speak 对话落库契约回归 (F1-1)。

单 NPC API `npc.speak` 没有世界层帮忙回流, 默认必须把"对方说的话"和"自己的
回复"写进该玩家的关系面; 世界层 talk 已用 perceive_action 观察过对方话语, 故
传 record_utterance=False 只补记回复, 不双写。
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from persona_agent import Location, NPC, World
from persona_agent.embeddings import HashEmbedder
from tests.test_persistence import _StubLLM, TRAITS


def _npc() -> NPC:
    return NPC("测试人", dict(TRAITS), llm=_StubLLM(),
               embedder=HashEmbedder())


def _obs_text(npc: NPC, player_id: str) -> str:
    return " | ".join(m.content for m in npc.store.all_valid(
        player_id=player_id, types=["observation"]))


def test_speak_writes_utterance_and_reply():
    npc = _npc()
    npc.observe("Aria 帮过我", 1.0, player_id="Aria")
    reply = npc.speak("Aria", "你还记得我吗?", 2.0)
    text = _obs_text(npc, "Aria")
    assert reply == "stub-reply"
    assert "Aria 对我说: 你还记得我吗?" in text, "对方话语必须落库"
    assert "我对 Aria 说: stub-reply" in text, "自己的回复必须落库"


def test_speak_remember_false_keeps_old_behavior():
    npc = _npc()
    npc.speak("Aria", "你好", 2.0, remember=False)
    assert npc.store.all_valid(player_id="Aria", types=["observation"]) == [], \
        "remember=False 时不写任何对话观察"


def test_speak_record_utterance_false_only_writes_reply():
    npc = _npc()
    npc.speak("Aria", "帮我看看炉子", 2.0, record_utterance=False)
    text = _obs_text(npc, "Aria")
    assert "我对 Aria 说: stub-reply" in text
    assert "帮我看看炉子" not in text, "record_utterance=False 不得重复记录对方话语"


def test_world_talk_does_not_duplicate_incoming(tmp_path):
    w = World("w", [Location("L", 0, 0)])
    w.add_npc("A", dict(TRAITS), llm=_StubLLM(),
              data_dir=str(tmp_path / "A"), location="L")
    w.add_npc("B", dict(TRAITS), llm=_StubLLM(),
              data_dir=str(tmp_path / "B"), location="L")
    w.execute_action(w.get("A"), {"action": "talk", "target": "B",
                                  "utterance": "你最近怎么样?"})
    b_text = _obs_text(w.npc("B"), "A")
    assert b_text.count("你最近怎么样") == 1, "目标 NPC 不应双写收到的同一句话"
    assert "我对 A 说: stub-reply" in b_text, "目标 NPC 应记得自己的回复"
    a_text = _obs_text(w.npc("A"), "B")
    assert "我对 B 说: 你最近怎么样?" in a_text
    assert "B 说: stub-reply" in a_text
    w.close()
