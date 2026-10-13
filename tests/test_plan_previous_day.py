"""日计划 previous_day 真实叙事测试 (L2 回归)。

previous_day 应是前一天的**真实活动** (库里的昨日计划记忆), 而非 0-based 天数
标签 ("第1天"其实是第二天, 对 LLM 无意义)。首日无计划时退回调用方标签。
无网络, 捕获型 stub LLM。
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from persona_agent import NPC
from tests.test_persistence import _StubLLM, TRAITS


class PlanCapturingLLM(_StubLLM):
    """记录 generate_plan 每次收到的 previous_day 参数。"""

    def __init__(self) -> None:
        super().__init__()
        self.previous_days: list[str] = []

    def generate_plan(self, persona_traits, previous_day, date, context=""):
        self.previous_days.append(previous_day)
        return super().generate_plan(persona_traits, previous_day, date, context)


def test_previous_day_is_real_narrative(tmp_path):
    """第二天生成计划时, previous_day 是昨日计划活动叙事, 不是天数标签。"""
    llm = PlanCapturingLLM()
    npc = NPC.create("Klaus", dict(TRAITS), llm=llm, data_dir=str(tmp_path))

    # 第一天: 库里无计划, 退回调用方标签
    npc.generate_daily_plan(previous_day="第0天", date="第1天", now=7.0)
    assert llm.previous_days[0] == "第0天", "首日无计划应退回调用方标签"

    # 第二天: 库里有第一天的计划记忆, previous_day 应是真实活动叙事
    npc.generate_daily_plan(previous_day="第1天", date="第2天", now=31.0)
    assert llm.previous_days[1].startswith("前一天活动: "), \
        f"第二天 previous_day 应是活动叙事, 实际: {llm.previous_days[1]!r}"
    assert "stub-activity" in llm.previous_days[1], \
        "叙事应包含昨日计划的活动内容"
    assert "第1天" != llm.previous_days[1], "不应是天数标签"


def test_previous_day_label_fallback_when_no_plan(tmp_path):
    """无计划记忆时退回标签 (不崩, 不产生空叙事)。"""
    llm = PlanCapturingLLM()
    npc = NPC.create("Klaus", dict(TRAITS), llm=llm, data_dir=str(tmp_path))
    npc.generate_daily_plan(previous_day="第0天", date="第1天", now=7.0)
    # 手动清掉计划记忆, 模拟"有标签但无计划"
    for p in npc.store.all_valid(types=["plan"]):
        npc.store.invalidate(p.id)
    npc.generate_daily_plan(previous_day="第1天", date="第2天", now=31.0)
    assert llm.previous_days[1] == "第1天", "无计划记忆应退回调用方标签"
