"""消融开关与实验埋点的离线测试 (无网络, stub LLM)。

覆盖 EvalPlan.md 的 P1-P7: 每个新构造参数的缺省行为 = 现行为, 非缺省臂的行为
被锁死。真实 LLM 下的消融臂效果由 evals/ 跑批验证, 这里只锁架构确定性。
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from persona_agent import NPC, MemoryRecord, MemoryStore, World, Location
from persona_agent.embeddings import HashEmbedder
from persona_agent.llm_real import RealLLM
from persona_agent.planning import PlanningEngine
from persona_agent.reflection import ReflectionEngine
from tests.test_persistence import _StubLLM
from tests.test_conflict_cost import CountingConflictLLM


# ---------------------------------------------------------------- 共用工厂
def _trust_store() -> MemoryStore:
    """一条帮助观察 (t=0) + 一条信任反思 (t=1)。"""
    store = MemoryStore(HashEmbedder())
    store.add(MemoryRecord(content="Aria 帮 Klaus 修好了咖啡机", timestamp=0.0,
                           type="observation", player_id="Aria", importance=7.0))
    store.add(MemoryRecord(content="Aria 是值得信赖的伙伴", timestamp=1.0,
                           type="reflection", player_id="Aria",
                           evidence=[], confidence=0.8, base_confidence=0.8))
    return store


def _add_betrayal(store: MemoryStore, ts: float, n: int) -> None:
    store.add(MemoryRecord(content=f"Aria 第{n}次背叛了 Klaus, 拿了钱跑路",
                           timestamp=ts, type="observation", player_id="Aria",
                           importance=8.0))


# ------------------------------------------------- P2: conflict_policy 分派
def test_policy_off_no_change_and_no_llm():
    """off 臂: 背叛观察之后反思原样保留 (不失效不衰减), 且零 LLM 调用。"""
    store = _trust_store()
    _add_betrayal(store, 2.0, 1)
    llm = CountingConflictLLM(default=9)   # 若误走 LLM 路径会被判强矛盾
    eng = ReflectionEngine(llm, HashEmbedder(), conflict_policy="off")
    assert eng.check_conflicts(store, "Aria", now=3.0) == []
    assert llm.calls == 0, "off 臂不应有任何 judge_conflict 调用"
    refs = store.all_valid(player_id="Aria", types=["reflection"])
    assert len(refs) == 1 and refs[0].valid and refs[0].confidence == pytest.approx(0.8)


def test_policy_heuristic_decays_without_invalidating():
    """heuristic_decay 臂: 信任反思撞上更晚的背叛观察 → 折半, 但不失效, 零 LLM。"""
    store = _trust_store()
    _add_betrayal(store, 2.0, 1)
    llm = CountingConflictLLM(default=9)
    eng = ReflectionEngine(llm, HashEmbedder(), conflict_policy="heuristic_decay")
    handled = eng.check_conflicts(store, "Aria", now=3.0)
    assert llm.calls == 0, "heuristic 臂零 LLM 调用 (旧词表机制)"
    assert len(handled) == 1
    ref = store.all_valid(player_id="Aria", types=["reflection"])[0]
    assert ref.valid, "本臂只衰减不失效 —— 与 LLM 臂的失效路径区分"
    assert ref.confidence == pytest.approx(0.8 * 0.5)


def test_policy_heuristic_idempotent_and_counting():
    """两条矛盾观察 → base*0.5**2; 重跑同一证据不重复折半 (幂等目标水位)。"""
    store = _trust_store()
    _add_betrayal(store, 2.0, 1)
    _add_betrayal(store, 3.0, 2)
    eng = ReflectionEngine(CountingConflictLLM(), HashEmbedder(),
                           conflict_policy="heuristic_decay")
    eng.check_conflicts(store, "Aria", now=4.0)
    first = store.all_valid(player_id="Aria", types=["reflection"])[0].confidence
    assert first == pytest.approx(0.8 * 0.25)
    eng.check_conflicts(store, "Aria", now=5.0)   # 同一组证据重跑
    second = store.all_valid(player_id="Aria", types=["reflection"])[0].confidence
    assert second == pytest.approx(first), "重跑不得再折半"


def test_policy_heuristic_reverse_direction():
    """反向: 不信任反思撞上更晚的信任观察同样衰减 (方向对称)。"""
    store = MemoryStore(HashEmbedder())
    store.add(MemoryRecord(content="Aria 欺骗了 Klaus", timestamp=0.0,
                           type="observation", player_id="Aria", importance=7.0))
    store.add(MemoryRecord(content="Aria 不可信, 以后要防备", timestamp=1.0,
                           type="reflection", player_id="Aria", evidence=[],
                           confidence=0.8, base_confidence=0.8))
    store.add(MemoryRecord(content="Aria 成了 Klaus 的朋友", timestamp=2.0,
                           type="observation", player_id="Aria", importance=7.0))
    eng = ReflectionEngine(CountingConflictLLM(), HashEmbedder(),
                           conflict_policy="heuristic_decay")
    eng.check_conflicts(store, "Aria", now=3.0)
    ref = store.all_valid(player_id="Aria", types=["reflection"])[0]
    assert ref.confidence == pytest.approx(0.4) and ref.valid


def test_policy_default_is_llm_path():
    """缺省 (full) 走 LLM 判别: 强矛盾仍失效 (锁住默认行为不变)。"""
    store = _trust_store()
    _add_betrayal(store, 2.0, 1)
    llm = CountingConflictLLM(default=9)
    ReflectionEngine(llm, HashEmbedder()).check_conflicts(store, "Aria", now=3.0)
    assert llm.calls >= 1, "缺省策略必须走 LLM 判别"
    assert store.all_valid(player_id="Aria", types=["reflection"]) == [], \
        "缺省策略下强矛盾仍失效 (现行为)"


# ------------------------------------------------- P1: evidence_types 开关
class _EvidenceRecordingLLM(_StubLLM):
    """记录 reflection_insights 收到的证据 id 列表 (stub 引全部传入证据)。"""

    def __init__(self) -> None:
        super().__init__()
        self.insight_evidence: list[list[int]] = []

    def reflection_insights(self, evidence, n: int = 5):
        self.insight_evidence.append([e[0] for e in evidence])
        return [("stub-insight", [e[0] for e in evidence])] if evidence else []


def _obs_and_ref_store() -> tuple[MemoryStore, int, int]:
    store = MemoryStore(HashEmbedder())
    obs_id = store.add(MemoryRecord(content="Aria 帮 Klaus 搬了货", timestamp=0.0,
                                    type="observation", player_id="Aria",
                                    importance=6.0))
    ref_id = store.add(MemoryRecord(content="Aria 是个热心肠", timestamp=1.0,
                                    type="reflection", player_id="Aria", evidence=[],
                                    confidence=0.7, base_confidence=0.7))
    return store, obs_id, ref_id


def test_evidence_default_only_observations():
    """缺省臂: 反思证据只含观察 id, 不含既有反思 id (级联切断不变)。"""
    store, obs_id, ref_id = _obs_and_ref_store()
    llm = _EvidenceRecordingLLM()
    ReflectionEngine(llm, HashEmbedder()).reflect_relationship(store, "Aria", now=2.0)
    new_refs = store.all_valid(player_id="Aria", types=["reflection"])
    newest = new_refs[-1]
    assert newest.evidence == [obs_id], f"证据应只有观察, 实际 {newest.evidence}"
    assert ref_id not in newest.evidence


def test_evidence_unconstrained_cites_reflections():
    """消融臂: 放开证据类型后, 反思可以引用既有反思 (Generative Agents 原始行为)。"""
    store, obs_id, ref_id = _obs_and_ref_store()
    llm = _EvidenceRecordingLLM()
    eng = ReflectionEngine(llm, HashEmbedder(),
                           evidence_types=("observation", "reflection"))
    eng.reflect_relationship(store, "Aria", now=2.0)
    newest = store.all_valid(player_id="Aria", types=["reflection"])[-1]
    assert ref_id in newest.evidence, "放开后反思应能引用反思"
    assert obs_id in newest.evidence


def test_evidence_min_relevance_filters_candidates():
    """候选证据限制: HashEmbedder 下零词面重叠的查询被 min_relevance 挡住。"""
    store, obs_id, _ref_id = _obs_and_ref_store()
    llm = _EvidenceRecordingLLM()
    # "stub-q" 与中文内容零词面重叠 → 相关性全 0 → 下限 0.5 挡掉全部候选
    eng = ReflectionEngine(llm, HashEmbedder(), evidence_min_relevance=0.5)
    new_ids = eng.reflect_relationship(store, "Aria", now=2.0)
    assert new_ids == [], "零相关候选应被下限剔除, 不产出无据反思"
    # 对照: 缺省 0.0 不过滤 (现行为)
    llm2 = _EvidenceRecordingLLM()
    ReflectionEngine(llm2, HashEmbedder()).reflect_relationship(store, "Aria", now=3.0)
    assert store.all_valid(player_id="Aria", types=["reflection"])[-1].evidence, \
        "缺省不过滤: 无据兜底引用 (宁宽勿断链) 仍然成立"


# ------------------------------------------------- P4: use_relationship 开关
def _react_npc(tmp_path, use_relationship: bool) -> NPC:
    npc = NPC("Testling", {"social": 0.8, "goal_oriented": 0.2},
              llm=_StubLLM(), embedder=HashEmbedder(),
              use_relationship=use_relationship)
    # 背叛历史 → stub 词表判出负信任
    npc.observe("Bram 偷走了 Klaus 的物品", 0.0, player_id="Bram")
    npc.observe("Bram 欺骗了 Klaus, 对他撒谎", 1.0, player_id="Bram")
    return npc


def test_use_relationship_flag_changes_utility(tmp_path):
    """False 臂: 背叛者信任被抹平, 效用与中立玩家相同; True 臂仍按信任打折。"""
    neutral_npc = NPC("Neutral", {"social": 0.8, "goal_oriented": 0.2},
                      llm=_StubLLM(), embedder=HashEmbedder())
    event = "Bram 邀请参加派对"
    u_on = _react_npc(tmp_path, use_relationship=True).react(event, "Bram", now=5.0).utility
    u_off = _react_npc(tmp_path, use_relationship=False).react(event, "Bram", now=5.0).utility
    u_neutral = neutral_npc.react("Bram 邀请参加派对", "Bram", now=5.0).utility
    assert u_on < 0 <= u_off, f"信任调制应在: 背叛者效用 {u_on} < 0"
    assert u_off == pytest.approx(u_neutral), \
        "关掉信任调制后, 背叛者与中立玩家效用必须相同"


# ------------------------------------------------- P5: RealLLM usage 计数
def test_llm_stats_count_failed_attempt():
    """不可达端点: 调用抛错, 但失败尝试也记账 (服务端资源已耗), usage 缺失记 0。"""
    llm = RealLLM(base_url="http://127.0.0.1:9", timeout=0.5, max_retries=0)
    with pytest.raises(RuntimeError):
        llm.score_importance("测试记忆")
    s = llm.stats
    assert s["calls"] == 1
    assert s["prompt_tokens"] == 0 and s["completion_tokens"] == 0
    assert s["by_method"]["score_importance"]["calls"] == 1
    assert s["total_latency_s"] >= 0.0
    llm.reset_stats()
    assert llm.stats["calls"] == 0


def test_llm_stats_default_zero():
    llm = RealLLM(base_url="http://127.0.0.1:9", timeout=0.5, max_retries=0)
    assert llm.stats["calls"] == 0 and llm.stats["by_method"] == {}


# ------------------------------------------------- P6: force_full_tier 开关
def test_force_full_tier_overrides_distance(tmp_path):
    """玩家远离 (视距外) 时距离调度给 idle, force_full_tier 覆盖为 full。"""
    w = World("测试镇", [Location("主城", 0, 0), Location("远郊", 5, 5)],
              force_full_tier=True)
    w.add_npc("测试人", {"social": 0.5, "goal_oriented": 0.5}, llm=_StubLLM(),
              embedder=HashEmbedder(), data_dir=str(tmp_path), location="主城")
    w.add_player("旅行者", "远郊")
    assert w.tier_of("测试人") == "idle", "距离调度本身应判 idle"
    tiers = w.schedule_tiers(now=0.0)
    assert tiers == {"测试人": "full"}, "force_full_tier 必须覆盖距离档位"
    w.close()


def test_default_world_still_distance_scheduled(tmp_path):
    w = World("测试镇", [Location("主城", 0, 0), Location("远郊", 5, 5)])
    w.add_npc("测试人", {"social": 0.5, "goal_oriented": 0.5}, llm=_StubLLM(),
              embedder=HashEmbedder(), data_dir=str(tmp_path), location="主城")
    w.add_player("旅行者", "远郊")
    assert w.schedule_tiers(now=0.0) == {"测试人": "idle"}, "缺省世界距离调度不变"
    w.close()


# ------------------------------------------------- P8: 档位决策门控
class _CountingDecideLLM(_StubLLM):
    def __init__(self) -> None:
        super().__init__()
        self.decide_calls = 0

    def decide_action(self, agent_name, goal, persona_traits, perception,
                      history, state):
        self.decide_calls += 1
        return super().decide_action(agent_name, goal, persona_traits,
                                     perception, history, state)


def test_decision_tier_gate_waits_for_idle(tmp_path):
    """门控开: 远离玩家的 idle NPC 走规则等待, 零 decide_action LLM 调用。"""
    w = World("测试镇", [Location("主城", 0, 0), Location("远郊", 5, 5)],
              decision_tier_gate=True)
    llm = _CountingDecideLLM()
    w.add_npc("测试人", {"social": 0.5, "goal_oriented": 0.5}, llm=llm,
              embedder=HashEmbedder(), data_dir=str(tmp_path), location="主城")
    w._agent_llms["测试人"] = llm   # 同 world_auto_sim 的自治注册惯例
    w._agent_personas["测试人"] = {"social": 0.5}
    w.add_player("旅行者", "远郊")
    _events, decisions = w.step_autonomous(now=8.0)
    assert decisions["测试人"]["action"] == "wait"
    assert "idle" in decisions["测试人"]["reason"]
    assert llm.decide_calls == 0, "idle NPC 门控后不应花决策 LLM 调用"
    w.close()


def test_decision_gate_default_off(tmp_path):
    """门控缺省关: idle NPC 照常走 LLM 决策 (现行为不变)。"""
    w = World("测试镇", [Location("主城", 0, 0), Location("远郊", 5, 5)])
    llm = _CountingDecideLLM()
    w.add_npc("测试人", {"social": 0.5, "goal_oriented": 0.5}, llm=llm,
              embedder=HashEmbedder(), data_dir=str(tmp_path), location="主城")
    w._agent_llms["测试人"] = llm   # 同 world_auto_sim 的自治注册惯例
    w._agent_personas["测试人"] = {"social": 0.5}
    w.add_player("旅行者", "远郊")
    _events, decisions = w.step_autonomous(now=8.0)
    assert llm.decide_calls == 1, "缺省世界 idle NPC 仍走 LLM 决策"
    assert decisions["测试人"]["action"] == "wait"   # stub 决策恒 wait
    w.close()


# ------------------------------------------------- 决策解析兜底
class _BrokenJsonDecideLLM(RealLLM):
    """_chat_json 恒抛 JSONDecodeError (模拟模型截断 JSON 的坏输出)。"""

    def _chat_json(self, system, user, **kw):
        import json
        raise json.JSONDecodeError("Unterminated string", user, 73)


def test_decide_action_falls_back_to_wait_on_bad_json():
    """一条坏输出不能拖垮整个 World.step: 解析失败兜底 wait 而非抛异常。"""
    llm = _BrokenJsonDecideLLM()
    d = llm.decide_action("测试人", "目标", {"social": 0.5}, "(空)", [], "健康")
    assert d["action"] == "wait"
    assert d["reason"] == "决策解析失败"


# ------------------------------------------------- P7: 规划计数
def test_planning_counters_increment():
    planner = PlanningEngine(_StubLLM())
    assert (planner.daily_plan_count, planner.replan_count) == (0, 0)
    store = MemoryStore(HashEmbedder())
    planner.make_daily_plan(store, {"social": 0.5}, "", "测试日", now=8.0)
    assert planner.daily_plan_count == 1
    planner.replan_from_now(store, {"social": 0.5}, now=12.0,
                            interruption="被火烧了")
    assert planner.replan_count == 1, "重规划必须计数 (打断率的分子)"


def test_npc_defaults_preserve_current_behavior():
    """缺省 NPC 的全套开关 = 现行为 (锁住'增量不改存量'的铁律)。"""
    npc = NPC("缺省人", {"social": 0.5}, llm=_StubLLM(), embedder=HashEmbedder())
    assert npc.reflection._conflict_policy == "full"
    assert npc.reflection._evidence_types == ("observation",)
    assert npc.reflection._evidence_min_relevance == 0.0
    assert npc.decider._use_relationship is True
    assert (npc.planner.daily_plan_count, npc.planner.replan_count) == (0, 0)
