"""传闻语义回归 (F4-1 / F4-2)。

- 只有与当前话题相关的传闻才被转述; 无关话题不会把第三方谣言塞给听者。
- 信任判断显式标注 `[传闻N跳]`; episode 继承传闻来源; 亲见可升级传闻记录。
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from persona_agent import Location, MemoryRecord, NPC, World
from persona_agent.embeddings import HashEmbedder
from tests.test_persistence import _StubLLM, TRAITS


class _CaptureTrust(_StubLLM):
    def __init__(self) -> None:
        super().__init__()
        self.calls = []

    def judge_trust(self, memories, player_id):
        self.calls.append(list(memories))
        return 0.0


def _npc() -> NPC:
    return NPC("测试人", dict(TRAITS), llm=_StubLLM(),
               embedder=HashEmbedder())


# ---------------------------------------------------------------- F4-1 转述
def _world(tmp_path) -> World:
    w = World("w", [Location("L", 0, 0)], rumor_spread=True)
    w.add_npc("A", dict(TRAITS), llm=_StubLLM(),
              data_dir=str(tmp_path / "A"), location="L")
    w.add_npc("B", dict(TRAITS), llm=_StubLLM(),
              data_dir=str(tmp_path / "B"), location="L")
    return w


def _talk(w: World, speaker: str, target: str, line: str, t: float) -> None:
    w.advance(t)
    w.execute_action(w.get(speaker), {"action": "talk", "target": target,
                                      "utterance": line})


def test_irrelevant_hearsay_not_retold(tmp_path):
    w = _world(tmp_path)
    a = w.get("A")
    w.npc("A").observe("C 说: 账本少了", 1.0, player_id="C",
                       hearsay=True, hop=1)
    _talk(w, "A", "B", "今天天气不错", 2.0)
    assert w.npc("B").store.all_valid(player_id="C") == [], \
        "聊天气不应把无关的 C 谣言转述给 B"
    _talk(w, "A", "B", "账本的事你听说了吗", 3.0)
    b_obs = w.npc("B").store.all_valid(player_id="C", types=["observation"])
    assert len(b_obs) == 1
    assert b_obs[0].hearsay and b_obs[0].hop == 2
    assert b_obs[0].content.startswith("A 告诉我: C 说:")
    w.close()


# ---------------------------------------------------------------- F4-2 信任
def test_trust_prompt_marks_hearsay_hops():
    llm = _CaptureTrust()
    npc = NPC("测试人", dict(TRAITS), llm=llm, embedder=HashEmbedder())
    npc.store.add(MemoryRecord(
        content="A 说: B 是骗子", timestamp=1.0, type="observation",
        player_id="A", hearsay=True, hop=2, importance=7.0))
    npc.store.add(MemoryRecord(
        content="A 帮了我", timestamp=2.0, type="observation",
        player_id="A", hearsay=False, hop=0, importance=7.0))
    npc.trust_toward("A")
    contents = [c for _t, c, _conf in llm.calls[-1]]
    assert any(c.startswith("[传闻2跳]") for c in contents)
    assert any(c == "A 帮了我" for c in contents)


def test_episode_inherits_hearsay_provenance():
    npc = _npc()
    npc.observe("B 说: A 偷了东西", 1.0, player_id="A",
                hearsay=True, hop=2)
    npc.observe("B 又说: A 和守卫吵了一架", 2.0, player_id="A",
                hearsay=True, hop=2)
    npc.consolidate(3.0)
    eps = npc.store.all_valid(types=["episode"])
    assert eps and eps[0].hearsay is True
    assert eps[0].hop == 2


def test_direct_observation_upgrades_hearsay_record():
    npc = _npc()
    npc.observe("A 偷了东西", 1.0, player_id="A", hearsay=True, hop=2)
    npc.observe("A 偷了东西", 2.0, player_id="A", hearsay=False, hop=0)
    obs = npc.store.all_valid(player_id="A", types=["observation"])
    assert len(obs) == 1
    assert obs[0].hearsay is False and obs[0].hop == 0, \
        "先听传闻、后亲眼见到应升级为亲见"


def test_hearsay_does_not_downgrade_direct_record():
    npc = _npc()
    npc.observe("A 帮了我", 1.0, player_id="A", hearsay=False, hop=0)
    npc.observe("A 帮了我", 2.0, player_id="A", hearsay=True, hop=2)
    obs = npc.store.all_valid(player_id="A", types=["observation"])
    assert len(obs) == 1
    assert obs[0].hearsay is False and obs[0].hop == 0, \
        "亲见记录不得被后来的传闻降级"
