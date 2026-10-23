"""per-agent / per-NPC 故障隔离回归 (F3-5)。

一次 LLM 超时、坏输出或 embedding 失败不能拖垮整步: 单个 agent 决策失败降级
wait, 单个 NPC 的规划/感知/固化失败不阻塞其余。
"""

from __future__ import annotations



from game_agent import Location, RealLLM, World
from tests.test_persistence import _StubLLM, TRAITS


class _BoomDecide(_StubLLM):
    def decide_action(self, *args, **kwargs):
        raise RuntimeError("LLM down")


class _CountingDecide(_StubLLM):
    def __init__(self) -> None:
        super().__init__()
        self.calls = 0

    def decide_action(self, *args, **kwargs):
        self.calls += 1
        return super().decide_action(*args, **kwargs)


class _BoomImportance(_StubLLM):
    def score_importance(self, text, player_id=None):
        raise RuntimeError("embedding down")


class _BoomPlan(_StubLLM):
    def generate_plan(self, *args, **kwargs):
        raise RuntimeError("plan failed")


class _GoodPlan(_StubLLM):
    def generate_plan(self, *args, **kwargs):
        return [(7, 9, "正常活动")]


def test_agent_decision_failure_does_not_stop_others(tmp_path):
    w = World("w", [Location("L", 0, 0)])
    w.add_npc("A", dict(TRAITS), llm=_BoomDecide(),
              data_dir=str(tmp_path / "A"), location="L")
    counter = _CountingDecide()
    w.add_npc("B", dict(TRAITS), llm=counter,
              data_dir=str(tmp_path / "B"), location="L")
    # F5-1 之前的临时注册: 本用例只验证故障隔离。
    w._agent_llms.update({"A": w.npc("A").llm, "B": counter})
    events, decisions = w.step_autonomous(1.0)
    assert decisions["A"]["action"] == "wait"
    assert "决策异常" in decisions["A"]["reason"]
    assert counter.calls == 1, "B 仍应被正常决策"
    assert events, "本步仍应产出事件"
    w.close()


def test_real_llm_decide_action_network_error_returns_wait(monkeypatch):
    llm = RealLLM()

    def boom(*args, **kwargs):
        raise RuntimeError("timeout")

    monkeypatch.setattr(llm, "_chat_json", boom)
    out = llm.decide_action("A", "goal", {}, "perception", [], "state")
    assert out["action"] == "wait"
    assert "解析失败" in out["reason"]


def test_plan_failure_isolated(tmp_path):
    w = World("w", [Location("L", 0, 0)])
    w.add_npc("A", dict(TRAITS), llm=_BoomPlan(),
              data_dir=str(tmp_path / "A"), location="L")
    w.add_npc("B", dict(TRAITS), llm=_GoodPlan(),
              data_dir=str(tmp_path / "B"), location="L")
    w.step(7.0)
    assert w.npc("B").store.all_valid(types=["plan"]), "B 仍应完成日计划"
    assert not w.npc("A").store.all_valid(types=["plan"]), "A 计划失败应被隔离"
    w.close()


def test_perceive_failure_isolated(tmp_path):
    w = World("w", [Location("L", 0, 0)])
    w.add_npc("A", dict(TRAITS), llm=_BoomImportance(),
              data_dir=str(tmp_path / "A"), location="L")
    w.add_npc("B", dict(TRAITS), llm=_StubLLM(),
              data_dir=str(tmp_path / "B"), location="L")
    w.add_player("P", "L")
    w.step(1.0)
    assert w.npc("B").store.all_valid(player_id="P", types=["observation"]), \
        "B 仍应完成感知"
    assert not w.npc("A").store.all_valid(player_id="P", types=["observation"]), \
        "A 感知失败应被隔离"
    w.close()


def test_world_event_failure_isolated(tmp_path):
    w = World("w", [Location("L", 0, 0)])
    w.add_npc("A", dict(TRAITS), llm=_BoomImportance(),
              data_dir=str(tmp_path / "A"), location="L")
    w.add_npc("B", dict(TRAITS), llm=_StubLLM(),
              data_dir=str(tmp_path / "B"), location="L")
    result = w.world_event("眼狩令颁布", 1.0)
    assert "B" in result and result["B"]
    assert "A" not in result, "A 的失败不应产生事件条目"
    w.close()


class _AttackThenBoomPlan(_StubLLM):
    def decide_action(self, *args, **kwargs):
        return {"action": "attack", "target": "B", "utterance": "",
                "dest": "", "reason": "test attack"}

    def generate_plan(self, *args, **kwargs):
        raise RuntimeError("replan failed")


def test_action_triggered_replan_failure_isolated(tmp_path):
    w = World("w", [Location("L", 0, 0)])
    atk = _AttackThenBoomPlan()
    w.add_npc("A", dict(TRAITS), llm=atk,
              data_dir=str(tmp_path / "A"), location="L")
    w.add_npc("B", dict(TRAITS), llm=_StubLLM(),
              data_dir=str(tmp_path / "B"), location="L")
    w._agent_llms.update({"A": atk, "B": w.npc("B").llm})
    w._agent_personas.update({"A": dict(TRAITS), "B": dict(TRAITS)})
    events, _decisions = w.step_autonomous(1.0)
    assert events and w.get("B").health < 100, "攻击仍应生效"
    w.close()
