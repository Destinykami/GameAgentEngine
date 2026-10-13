"""计划生命周期测试 (M4 + M5 回归)。

M4: 新一天的日计划**替换**旧计划 —— 昨日计划 (含分解子任务) 失效, 不再降权到
    地板留在流里污染检索; 今日计划为空时昨日计划也照旧失效。
M5: 自治模拟里重大状态变化 (战斗/逃跑/帮匿) 打断当日计划 → 从当前时刻重规划;
    talk/move/wait 不打断; 死者不重规划也不再规划 (生命止于死亡)。
无网络, stub LLM。
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from persona_agent import MemoryStore
from persona_agent.embeddings import HashEmbedder
from persona_agent.planning import PlanningEngine
from persona_agent.world import World, Location
from tests.test_persistence import _StubLLM, TRAITS


class EmptyPlanLLM(_StubLLM):
    def generate_plan(self, persona_traits, previous_day, date, context=""):
        return []   # M3 空计划: LLM 返回空


class ScriptedAgentLLM(_StubLLM):
    """decide_action 按脚本队列返回动作 (空则 wait); generate_plan 回 (14,16)
    的未来块, 使 13 点锚定的重规划不被裁空。"""

    def __init__(self, script: list[dict] | None = None) -> None:
        super().__init__()
        self._script = list(script or [])

    def decide_action(self, agent_name, goal, persona_traits, perception,
                      history, state):
        if self._script:
            return self._script.pop(0)
        return {"action": "wait", "target": "", "utterance": "",
                "dest": "", "reason": "scripted-wait"}

    def generate_plan(self, persona_traits, previous_day, date, context=""):
        return [(14, 16, "stub-activity")]


# ---------------------------------------------------------------- M4: 跨日失效
def test_new_day_plan_invalidates_old_plans():
    """第二天生成日计划: 昨日计划 (含子任务) 全部失效, 只留新的一天。"""
    store = MemoryStore(HashEmbedder())
    planner = PlanningEngine(_StubLLM())
    planner.make_daily_plan(store, TRAITS, "第1天", "第2天", now=7.0)
    day1 = store.all_valid(types=["plan"])
    assert len(day1) == 2, "stub: 1 顶层块 + 1 子任务"
    planner.make_daily_plan(store, TRAITS, "第2天", "第3天", now=31.0)
    valid_ids = {m.id for m in store.all_valid(types=["plan"])}
    assert not any(p.id in valid_ids for p in day1), "昨日计划应失效"
    assert len(valid_ids) == 2, "只留新一天的计划"


def test_empty_plan_still_invalidates_old():
    """今日计划为空 (LLM 返回空): 昨日计划仍失效 —— 新的一天已开始。"""
    store = MemoryStore(HashEmbedder())
    PlanningEngine(_StubLLM()).make_daily_plan(
        store, TRAITS, "第1天", "第2天", now=7.0)
    assert len(store.all_valid(types=["plan"])) == 2
    ids, blocks = PlanningEngine(EmptyPlanLLM()).make_daily_plan(
        store, TRAITS, "第2天", "第3天", now=31.0)
    assert blocks == [] and ids == []
    assert store.all_valid(types=["plan"]) == [], "空计划也清掉昨日计划"


# ---------------------------------------------------------------- M5: 打断重规划
def _two_npc_world(tmp_path):
    """桃音与刚郎同在治疗堂 (距离 0), 各自脚本化决策 LLM。"""
    w = World("稻妻城", [
        Location("主城街道", 0, 0), Location("治疗堂", 1, 0),
        Location("锻造坊", 2, 0), Location("眼狩署", 0, 1),
        Location("神樱庭", 0, 3)], path=os.path.join(str(tmp_path), "world.db"))
    m_llm = ScriptedAgentLLM()
    g_llm = ScriptedAgentLLM()
    w.add_npc("桃音", TRAITS, llm=m_llm, data_dir=str(tmp_path), location="治疗堂")
    w.add_npc("刚郎", TRAITS, llm=g_llm, data_dir=str(tmp_path), location="治疗堂")
    w._agent_llms["桃音"] = m_llm   # 模拟脚本同款: 注册决策 LLM
    w._agent_llms["刚郎"] = g_llm
    return w, m_llm, g_llm


def test_interrupting_actions_trigger_replan(tmp_path):
    """攻击: 双方重规划; 逃跑: 仅行动者重规划; 对话: 无人重规划。"""
    w, m_llm, g_llm = _two_npc_world(tmp_path)
    m_llm._script.append({"action": "attack", "target": "刚郎"})
    w.step_autonomous(now=13.0)   # 日计划门先触发 (各 2 条晨间计划)

    momone, gorou = w.npc("桃音"), w.npc("刚郎")
    mp = [m.content for m in momone.store.all_valid(types=["plan"])]
    assert len(mp) == 1 and mp[0].startswith("[重规划]"), \
        "攻击者的晨间计划失效, 只留重规划块"
    gp = [m.content for m in gorou.store.all_valid(types=["plan"])]
    assert len(gp) == 1 and gp[0].startswith("[重规划]"), "挨打者 (活着) 也重规划"
    assert any("计划被打断" in c and "刚郎" in c
               for c in (m.content for m in momone.store.all_valid(
                   types=["observation"]))), "攻击者的中断原因应记入观察"
    assert any("被 桃音 攻击了" in c
               for c in (m.content for m in gorou.store.all_valid(
                   types=["observation"]))), "受害者的中断原因应记入观察"

    # 14:00 逃跑 (刚郎同地 = 威胁) —— 只有行动者重规划
    m_llm._script.append({"action": "flee"})
    w.step_autonomous(now=14.0)
    mp2 = [m.content for m in momone.store.all_valid(types=["plan"])]
    assert len(mp2) == 1 and mp2[0].startswith("[重规划]"), "逃跑后重规划"
    g_obs = [m.content for m in gorou.store.all_valid(types=["observation"])]
    assert sum(1 for c in g_obs if "计划被打断" in c) == 1, "观望不触发重规划"

    # 15:00 对话 —— 日程内的日常行为, 无人重规划
    m_llm._script.append({"action": "talk", "target": "刚郎",
                          "utterance": "辛苦了"})
    plans_before = [m.id for m in momone.store.all_valid(types=["plan"])]
    w.step_autonomous(now=15.0)
    assert [m.id for m in momone.store.all_valid(types=["plan"])] == plans_before, \
        "对话不打断日程"
    w.close()


def test_dead_npc_skips_planning(tmp_path):
    """死者: 被击杀不重规划 (晨间计划原样保留), 次日早晨也不再规划。"""
    w, m_llm, g_llm = _two_npc_world(tmp_path)
    w.get("刚郎").health = 5
    m_llm._script.append({"action": "attack", "target": "刚郎"})
    w.step_autonomous(now=13.0)

    assert w.get("刚郎").dead, "低血量受害者阵亡"
    gorou = w.npc("刚郎")
    assert len(gorou.store.all_valid(types=["plan"])) == 2, \
        "死者不重规划, 晨间计划原样保留 (生命止于死亡)"
    assert not any("计划被打断" in m.content
                   for m in gorou.store.all_valid(types=["observation"]))
    assert len(w.npc("桃音").store.all_valid(types=["plan"])) == 1, \
        "攻击者正常重规划"

    # 次日 13:00: 日计划门再次触发 —— 活着的桃音换日计划, 死去的刚郎跳过
    w.step_autonomous(now=37.0)   # 桃音脚本空 → 观望
    momone_plans = w.npc("桃音").store.all_valid(types=["plan"])
    assert len(momone_plans) == 2, "次日日计划替换重规划块 (M4 跨日清理)"
    assert not any(p.content.startswith("[重规划]") for p in momone_plans)
    assert len(gorou.store.all_valid(types=["plan"])) == 2, \
        "死者的日计划被跳过, 旧计划冻结"
    w.close()
