"""计划→反应链路测试 (H3 回归): react() 必须拿到"当前时刻正在进行的计划块",
而非"日计划已生成"空话 —— score_event 需要知道 NPC 正忙什么才能判断
目标契合度 (v_goal) 与打断代价 (c_interrupt)。

无网络, stub LLM。断言通过记录 score_event 实际收到的 plan 参数。
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from persona_agent import NPC
from tests.test_persistence import _StubLLM, TRAITS

DAY_BLOCKS = [(7, 9, "起床整理"), (9, 12, "备货咖啡豆"), (12, 13, "午餐")]
REPLAN_BLOCKS = [(7, 9, "起床整理")]   # 重规划 stub: 只生成早间块, 不覆盖午后


class PlanStubLLM(_StubLLM):
    """日计划返回固定多块; 重规划返回不覆盖午后的块; 记录 score_event 收到的 plan。"""

    def __init__(self) -> None:
        super().__init__()
        self.seen_plans: list[str] = []

    def generate_plan(self, persona_traits, previous_day, date, context=""):
        if date == "replan":
            return list(REPLAN_BLOCKS)
        return list(DAY_BLOCKS)

    def score_event(self, event, persona_traits, current_plan=""):
        self.seen_plans.append(current_plan)
        return super().score_event(event, persona_traits, current_plan)


def _make(tmp_path) -> tuple[NPC, PlanStubLLM]:
    llm = PlanStubLLM()
    return NPC.create("Plan", dict(TRAITS), llm=llm, data_dir=str(tmp_path)), llm


def test_react_uses_active_plan_block(tmp_path):
    """计划覆盖当前时刻: react 拿到该块的活动, 不再是"日计划已生成"。"""
    npc, llm = _make(tmp_path)
    npc.generate_daily_plan(previous_day="", date="第一天", now=7.0)
    npc.react("Aria 邀请 Plan 参加派对", "Aria", now=9.5)   # 9.5 ∈ [9,12)
    assert llm.seen_plans, "score_event 应被调用"
    assert llm.seen_plans[-1] == "备货咖啡豆", "应传入当前正在进行的计划块活动"
    assert llm.seen_plans[-1] != "日计划已生成"


def test_react_empty_plan_when_no_block_covers_now(tmp_path):
    """计划未覆盖当前时刻: plan 为空串 (score_event 会判'当前没有特别重要的计划')。"""
    npc, llm = _make(tmp_path)
    npc.generate_daily_plan(previous_day="", date="第一天", now=7.0)
    npc.react("Aria 邀请 Plan 参加派对", "Aria", now=13.5)   # 13.5 无块覆盖
    assert llm.seen_plans[-1] == ""


def test_replan_interruption_fallback(tmp_path):
    """重规划块未覆盖当前时刻时, 中断原因作兜底 (保持既有 replan 语义)。"""
    npc, llm = _make(tmp_path)
    npc.generate_daily_plan(previous_day="", date="第一天", now=7.0)
    npc.replan(now=13.5, interruption="处理火灾")            # 重规划块只有早间
    npc.react("Bram 邀请 Plan 打牌", "Bram", now=13.5)
    assert llm.seen_plans[-1] == "处理火灾"


def test_explicit_current_plan_wins(tmp_path):
    """显式 current_plan 参数优先级最高。"""
    npc, llm = _make(tmp_path)
    npc.generate_daily_plan(previous_day="", date="第一天", now=7.0)
    npc.react("Aria 邀请 Plan 参加派对", "Aria", now=9.5, current_plan="正在修咖啡机")
    assert llm.seen_plans[-1] == "正在修咖啡机"
