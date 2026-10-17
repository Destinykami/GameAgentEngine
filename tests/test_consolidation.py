"""记忆固化 (M1) / 冲突扫描收窄 (M2) / 身份层信念 (M3) 测试, 无网络。

M1: 夜间固化把当天原始观察按流压成 episode, 源观察标 consolidated (仍 valid
可检索, 退出冲突扫描), 幂等。M2: 固化后冲突扫描只见 episode + 未固化观察
(二次成本 → 线性)。M3: 身份信念跨玩家泛化, 写共享流独立 type 池, 可选注入
决策上下文。全部显式触发/缺省关 = 现行为。
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from persona_agent import NPC
from tests.test_persistence import _StubLLM

TRAITS = {"social": 0.7, "goal_oriented": 0.5}


class _CountingConflictLLM(_StubLLM):
    def __init__(self) -> None:
        super().__init__()
        self.conflict_calls = 0

    def judge_conflict(self, reflection, observation):
        self.conflict_calls += 1
        return super().judge_conflict(reflection, observation)


class _PerceptionCapturingLLM(_StubLLM):
    def __init__(self) -> None:
        super().__init__()
        self.perceptions: list[str] = []

    def decide_action(self, agent_name, goal, persona_traits, perception,
                      history, state):
        self.perceptions.append(perception)
        return super().decide_action(agent_name, goal, persona_traits,
                                     perception, history, state)


class _IdentityEvidenceCapturingLLM(_StubLLM):
    """记录 reflection_insights 收到的证据 (验证身份信念的跨流原料注入)。"""

    def __init__(self) -> None:
        super().__init__()
        self.identity_evidence: list[list[int]] = []

    def reflection_insights(self, evidence, n: int = 5):
        if evidence:
            self.identity_evidence.append([e[0] for e in evidence])
        return super().reflection_insights(evidence, n)


def _npc(tmp_path) -> NPC:
    return NPC.create("测试人", dict(TRAITS), llm=_StubLLM(),
                      data_dir=str(tmp_path / "测试人"))


# ---------------------------------------------------------------- M1 固化
def test_consolidate_creates_episode(tmp_path):
    """当天 ≥2 条观察按流压成 episode, 源观察标 consolidated 但仍 valid。"""
    npc = _npc(tmp_path)
    npc.observe("P 帮忙修好了炉子", 10.0, player_id="P")
    npc.observe("P 又送来了炭", 12.0, player_id="P")
    npc.observe("镇上来了眼狩队", 11.0)    # 共享流两条, 单独压一条
    npc.observe("眼狩署方向冒烟", 11.5)
    ids = npc.consolidate(13.0)
    assert len(ids) == 2   # P 面一条 + 共享流一条
    eps = npc.store.all_valid(types=["episode"])
    assert len(eps) == 2
    p_eps = [e for e in eps if e.player_id == "P"]
    assert len(p_eps) == 1
    assert p_eps[0].evidence and all(
        isinstance(i, int) for i in p_eps[0].evidence)
    # 源观察: consolidated=True, 仍 valid 可检索
    p_obs = npc.store.all_valid(player_id="P", types=["observation"])
    assert len(p_obs) == 2 and all(o.consolidated for o in p_obs)
    assert all(o.valid for o in p_obs)
    npc.store.close()


def test_consolidate_single_obs_skipped(tmp_path):
    """单条观察不压 (本身已是摘要); 早于 24h 窗口的不压。"""
    npc = _npc(tmp_path)
    npc.observe("只有这一条", 10.0, player_id="P")
    npc.observe("很久以前的观察", -100.0)
    assert npc.consolidate(11.0) == []
    npc.store.close()


def test_consolidate_idempotent(tmp_path):
    """同一天重跑: consolidated 观察不再被捡起, 不产生新 episode。"""
    npc = _npc(tmp_path)
    npc.observe("观察一", 10.0, player_id="P")
    npc.observe("观察二", 12.0, player_id="P")
    npc.consolidate(13.0)
    assert len(npc.store.all_valid(types=["episode"])) == 1
    assert npc.consolidate(14.0) == []
    assert len(npc.store.all_valid(types=["episode"])) == 1
    npc.store.close()


def test_consolidate_confidence_and_importance(tmp_path):
    """episode 置信度 = 源观察最低 confidence, importance = 源观察最高。"""
    npc = _npc(tmp_path)
    npc.observe("观察一", 10.0, player_id="P")
    npc.observe("观察二", 12.0, player_id="P")
    # 人为把其中一条的 importance 调到不同值 (验证取 max)
    obs = npc.store.all_valid(player_id="P", types=["observation"])
    npc.store.update_confidence(obs[0].id, 0.6)   # 置信度 0.6 < 1.0
    npc.consolidate(13.0)
    ep = [e for e in npc.store.all_valid(types=["episode"])
          if e.player_id == "P"][0]
    assert ep.confidence == 0.6
    assert ep.importance == 5.0
    npc.store.close()


def test_world_consolidation_flag(tmp_path):
    """世界层固化: 缺省关时 23 点不固化; 开时在 consolidate_hour 触发, 一天一次。"""
    from persona_agent.world import World, Location
    w = World("城", [Location("甲", 0, 0)], path=None)
    w.add_player("玩家", "甲")
    w.add_npc("A", dict(TRAITS), llm=_StubLLM(), data_dir=str(tmp_path / "A"),
              location="甲")
    w.advance(10.0)
    w.npc("A").observe("观察一", 10.0)
    w.npc("A").observe("观察二", 12.0)
    # 缺省关: 到 23 点也不固化
    w.step(23.0)
    assert w.npc("A").store.all_valid(types=["episode"]) == []
    w.close()

    w2 = World("城", [Location("甲", 0, 0)], path=None, consolidation=True,
               consolidate_hour=23.0)
    w2.add_player("玩家", "甲")
    w2.add_npc("A", dict(TRAITS), llm=_StubLLM(), data_dir=str(tmp_path / "B"),
               location="甲")
    w2.advance(10.0)
    w2.npc("A").observe("观察一", 10.0)
    w2.npc("A").observe("观察二", 12.0)
    w2.step(23.0)
    assert len(w2.npc("A").store.all_valid(types=["episode"])) == 1
    # 同一天再 step 不重复固化
    w2.step(23.5)
    assert len(w2.npc("A").store.all_valid(types=["episode"])) == 1
    w2.close()


# ---------------------------------------------------------------- M2 扫描收窄
def test_conflict_scan_skips_consolidated(tmp_path):
    """固化前: 反思 × 10 条更晚观察 → 10 次矛盾判定;
    固化后: 只判 episode 一条 → 1 次 (K 窗口内)。"""
    llm = _CountingConflictLLM()
    npc = NPC("测试人", dict(TRAITS), llm=llm)
    npc.observe("P 帮过我", 1.0, player_id="P")
    npc.observe("P 又送来了炭", 2.0, player_id="P")
    npc.reflect_relationship("P", 5.0)   # 反思 (t=5), 证据 = 前两条观察
    for i in range(10):
        npc.observe(f"P 的第 {i} 条更晚观察", 6.0 + i, player_id="P")
    npc.reflection.check_conflicts(npc.store, "P", 16.0)
    assert llm.conflict_calls == 10       # 10 条更晚观察 (K=10 窗口全收)
    npc.consolidate(17.0)                 # 全部观察 → 1 条 episode (t=17)
    npc.reflection.check_conflicts(npc.store, "P", 17.5)
    assert llm.conflict_calls == 11       # 只多判了 episode 一条 (新证据对)


# ---------------------------------------------------------------- M3 身份信念
def test_identity_belief_cross_player(tmp_path):
    """身份信念: 跨玩家泛化, 写共享流 type=identity; LLM 收到的证据含
    各玩家面关系反思 (泛化原料) —— 这是跨流性的直接证据。"""
    capturing = _IdentityEvidenceCapturingLLM()
    npc = NPC.create("测试人", dict(TRAITS), llm=capturing,
                     data_dir=str(tmp_path / "测试人"))
    npc.observe("P 帮过我", 10.0, player_id="P")
    npc.reflect_relationship("P", 11.0)   # P 面关系反思
    npc.observe("Q 背叛过我", 12.0, player_id="Q")
    npc.reflect_relationship("Q", 13.0)   # Q 面关系反思
    npc.observe("世界动荡", 14.0)          # 共享流观察
    ids = npc.reflect_identity(15.0)
    assert len(ids) >= 1
    ident = npc.store.all_valid(shared=True, types=["identity"])
    assert len(ident) == 1
    p_ref = npc.store.all_valid(player_id="P", types=["reflection"])
    q_ref = npc.store.all_valid(player_id="Q", types=["reflection"])
    # 身份信念的证据注入 (最后一次 reflection_insights 调用 = 身份反思)
    fed = set(capturing.identity_evidence[-1])
    assert p_ref[0].id in fed and q_ref[0].id in fed
    npc.store.close()


def test_identity_isolated_from_reflection_pool(tmp_path):
    """身份信念在独立 type 池: 不进 ["reflection"] 过滤 (不被当关系反思),
    也不进证据约束链 (evidence_types 锁 observation)。"""
    npc = _npc(tmp_path)
    npc.observe("P 帮过我", 10.0, player_id="P")
    npc.reflect_relationship("P", 11.0)
    npc.reflect_identity(12.0)
    refs = npc.store.all_valid(types=["reflection"])
    assert all(r.type != "identity" for r in refs)
    # 自我反思证据检索 (types=["observation"]) 不会把 identity 当证据
    evidence = npc.store.retrieve(query="我是谁", now=13.0, shared=True,
                                  types=["observation"])
    assert all(e["type"] != "identity" for e in evidence)
    npc.store.close()


def test_identity_injection_into_decision(tmp_path):
    """身份信念注入决策上下文: 开关开 → perception 含身份信念; 缺省关 → 不含。"""
    from persona_agent.world import World, Location
    w = World("城", [Location("甲", 0, 0)], path=None,
              use_identity_beliefs=True)
    w.add_player("玩家", "甲")
    capturing = _PerceptionCapturingLLM()
    w.add_npc("A", dict(TRAITS), llm=capturing, data_dir=str(tmp_path / "A"),
              location="甲")
    w.advance(10.0)
    w.npc("A").observe("P 帮过我", 10.0, player_id="玩家")
    w.npc("A").reflect_relationship("玩家", 11.0)
    w.npc("A").reflect_identity(12.0)
    w._agent_llms["A"] = capturing        # 白盒: 把 NPC 注册成 agent
    w.decide_agent(w.get("A"), "")
    assert any("身份信念" in p for p in capturing.perceptions)
    w.close()

    w2 = World("城", [Location("甲", 0, 0)], path=None)   # 缺省关
    w2.add_player("玩家", "甲")
    capturing2 = _PerceptionCapturingLLM()
    w2.add_npc("A", dict(TRAITS), llm=capturing2,
               data_dir=str(tmp_path / "B"), location="甲")
    w2.advance(10.0)
    w2.npc("A").observe("P 帮过我", 10.0, player_id="玩家")
    w2.npc("A").reflect_relationship("玩家", 11.0)
    w2.npc("A").reflect_identity(12.0)
    w2._agent_llms["A"] = capturing2
    w2.decide_agent(w2.get("A"), "")
    assert not any("身份信念" in p for p in capturing2.perceptions)
    w2.close()
