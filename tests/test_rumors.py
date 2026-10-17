"""谣言传播 (S4) 与内生事件 (S5) 测试, 无网络。

S4: talk 的话语被范围内第三方 NPC 听到 (传闻 hop=1), 持有未封顶传闻的 NPC
下次谈吐时转述给对话者 (hop+1), 3 跳封顶; 传闻检索按跳数打折 (每跳 ×0.8)。
S5: 同一 actor 对同一 target 连续同型动作达阈值触发世界事件, 断链清零。
全部缺省关 = 现行为 (前两项测试锁死缺省零行为)。
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from persona_agent.memory import MemoryStore, MemoryRecord, HEARSAY_DECAY
from persona_agent import HashEmbedder
from persona_agent.world import World, Location, Player
from tests.test_persistence import _StubLLM

TRAITS = {"social": 0.7, "goal_oriented": 0.5}


def _locs() -> list[Location]:
    # 甲乙相邻 (距离 1.0 ≤ 视距 1.5), 丙远 (距离 3.0 > 视距)
    return [Location("甲", 0, 0), Location("乙", 0, 1), Location("丙", 0, 3)]


def _world(tmp_path, **kw) -> World:
    w = World("测试城", _locs(), path=None, **kw)
    w.add_player("玩家", "甲")
    w.add_npc("A", dict(TRAITS), llm=_StubLLM(), data_dir=str(tmp_path / "A"),
              location="甲")
    w.add_npc("B", dict(TRAITS), llm=_StubLLM(), data_dir=str(tmp_path / "B"),
              location="甲")
    w.add_npc("C", dict(TRAITS), llm=_StubLLM(), data_dir=str(tmp_path / "C"),
              location="乙")
    # D 在丙: 离甲 3.0 (听不见 A 的原话), 离乙 1.0 (C 转述时在场)
    w.add_npc("D", dict(TRAITS), llm=_StubLLM(), data_dir=str(tmp_path / "D"),
              location="丙")
    w.add_npc("E", dict(TRAITS), llm=_StubLLM(), data_dir=str(tmp_path / "E"),
              location="丙")
    w.add_npc("F", dict(TRAITS), llm=_StubLLM(), data_dir=str(tmp_path / "F"),
              location="丙")
    w.schedule_tiers(10.0)
    return w


def _talk(w: World, speaker: str, target: str, line: str, t: float) -> None:
    w.advance(t)
    w.execute_action(w.get(speaker), {"action": "talk", "target": target,
                                      "utterance": line})


# ---------------------------------------------------------------- 缺省零行为
def test_rumor_default_off(tmp_path):
    w = _world(tmp_path)   # 缺省 rumor_spread=False
    _talk(w, "A", "B", "账本少了", 10.0)
    # C (乙, 距离 1.0 在视距内) 没听到; E (丙) 更没听到
    assert w.npc("C").store.all_valid() == []
    assert w.npc("E").store.all_valid() == []
    w.close()


def test_chain_rule_default_none(tmp_path):
    """无规则注册时, 连续攻击不产生任何世界事件。"""
    w = _world(tmp_path)
    t = w.add_player("目标", "甲")
    for i in range(5):
        _talk(w, "A", "目标", "x", 10.0 + i)
        w.execute_action(w.get("A"), {"action": "attack", "target": "目标"})
    assert w.npc("C").store.all_valid() == []   # 无世界事件观察
    w.close()


# ---------------------------------------------------------------- S4 听见
def test_overhearing_hop1(tmp_path):
    w = _world(tmp_path, rumor_spread=True)
    _talk(w, "A", "B", "账本少了", 10.0)
    # C (乙, 视距内) 听到, 观察进 A 的关系流 (player_id=A), hearsay hop=1
    c_obs = w.npc("C").store.all_valid(player_id="A", types=["observation"])
    assert len(c_obs) == 1
    assert c_obs[0].hearsay and c_obs[0].hop == 1
    assert c_obs[0].content == "A 说: 账本少了"
    # E (丙, 视距外) 没听到
    assert w.npc("E").store.all_valid(player_id="A") == []
    # B 是对话者不是第三方: B 只有 E16 的亲见观察 (hearsay=False), 无传闻
    b_obs = w.npc("B").store.all_valid(player_id="A", types=["observation"])
    assert len(b_obs) == 1 and not b_obs[0].hearsay
    w.close()


def test_overhearing_dead_npc_skipped(tmp_path):
    w = _world(tmp_path, rumor_spread=True)
    w.get("C").dead = True
    _talk(w, "A", "B", "账本少了", 10.0)
    assert w.npc("C").store.all_valid(player_id="A") == []
    w.close()


# ---------------------------------------------------------------- S4 转述链
def test_retell_chain_and_cap(tmp_path):
    """A→B 的话 C 听到 (hop1) → C 转述 D (hop2) → D 转述 E (hop3) → E 封顶不转。"""
    w = _world(tmp_path, rumor_spread=True)
    _talk(w, "A", "B", "账本少了", 10.0)          # C 听到 hop1
    assert w.npc("C").store.all_valid(player_id="A")[0].hop == 1

    _talk(w, "C", "D", "随便聊聊", 11.0)           # C 转述给 D → hop2
    d_obs = w.npc("D").store.all_valid(player_id="A", types=["observation"])
    assert len(d_obs) == 1
    assert d_obs[0].hop == 2 and d_obs[0].hearsay
    assert d_obs[0].content == "A 说: 账本少了"

    _talk(w, "D", "E", "随便聊聊", 12.0)           # D 转述给 E → hop3
    e_obs = w.npc("E").store.all_valid(player_id="A", types=["observation"])
    assert len(e_obs) == 1 and e_obs[0].hop == 3

    _talk(w, "E", "F", "随便聊聊", 13.0)           # E 的传闻 hop3 已封顶 → 不转
    assert w.npc("F").store.all_valid(player_id="A") == []
    w.close()


def test_retell_triangle_no_hop_escalation(tmp_path):
    """三角传回: D 把转述传回 C, C 已有同内容同流传闻 → 去重合并, hop 不升级。"""
    w = _world(tmp_path, rumor_spread=True)
    _talk(w, "A", "B", "账本少了", 10.0)           # C hop1
    _talk(w, "C", "D", "随便聊聊", 11.0)           # D hop2
    _talk(w, "D", "C", "随便聊聊", 12.0)           # D 转述回 C → 合并, hop 仍 1
    c_obs = w.npc("C").store.all_valid(player_id="A", types=["observation"])
    assert len(c_obs) == 1
    assert c_obs[0].hop == 1
    w.close()


def test_overhear_repeat_merges(tmp_path):
    """同一句话重复被听到: 去重合并, 记录数与 hop 都不变。"""
    w = _world(tmp_path, rumor_spread=True)
    _talk(w, "A", "B", "账本少了", 10.0)
    _talk(w, "A", "B", "账本少了", 11.0)
    c_obs = w.npc("C").store.all_valid(player_id="A", types=["observation"])
    assert len(c_obs) == 1 and c_obs[0].hop == 1
    w.close()


# ---------------------------------------------------------------- S4 检索折扣
def test_hearsay_retrieval_discount():
    """同内容亲见 vs 传闻: 检索分数按 0.8^hop 打折, 亲见恒在前。"""
    store = MemoryStore(HashEmbedder())
    store.add(MemoryRecord(content="A 说: 账本少了", timestamp=10.0,
                           player_id="A", importance=5.0))
    store.add(MemoryRecord(content="A 说: 账本少了", timestamp=10.0,
                           player_id="A", importance=5.0,
                           hearsay=True, hop=1))
    res = store.retrieve(query="A 说 账本", now=11.0, player_id="A",
                         mark_accessed=False)
    assert len(res) == 2
    assert res[0]["hearsay"] is False and res[1]["hearsay"] is True
    ratio = res[1]["score"] / res[0]["score"]
    assert abs(ratio - HEARSAY_DECAY) < 1e-9
    store.close()


# ---------------------------------------------------------------- S5 内生事件
def test_chain_rule_fires(tmp_path):
    """连续 3 次攻击触发世界事件, 触发后清零 (第 4 次不重复触发)。"""
    w = _world(tmp_path, rumor_spread=True)
    w.add_chain_rule("attack", 3, "署内问责: 搜查反复无果")
    t = w.add_player("目标", "甲")
    for i in range(4):
        w.advance(10.0 + i)
        w.execute_action(w.get("A"), {"action": "attack", "target": "目标"})
    # 世界事件观察进同区域 NPC 的共享流 (player_id=None)
    a_obs = w.npc("A").store.all_valid(shared=True, types=["observation"])
    fired = [m for m in a_obs if m.content == "署内问责: 搜查反复无果"]
    assert len(fired) == 1   # 第 3 次触发一次, 第 4 次未再触发
    # 结构化视觉事件也记录了世界事件
    assert any(ve.type == "world_event" for ve in w.visual_events)
    w.close()


def test_chain_break_resets(tmp_path):
    """断链: 期间做别的带目标动作, 链清零重新累积 (2+2 不触发)。"""
    w = _world(tmp_path, rumor_spread=True)
    w.add_chain_rule("attack", 3, "署内问责")
    t = w.add_player("目标", "甲")
    for i in range(2):
        w.advance(10.0 + i)
        w.execute_action(w.get("A"), {"action": "attack", "target": "目标"})
    _talk(w, "A", "目标", "插一句", 12.0)          # 断链
    for i in range(2):
        w.advance(13.0 + i)
        w.execute_action(w.get("A"), {"action": "attack", "target": "目标"})
    a_obs = w.npc("A").store.all_valid(shared=True, types=["observation"])
    assert not [m for m in a_obs if m.content == "署内问责"]
    w.close()
