"""计划输出解析测试 (M3 回归): LLM 计划 JSON 过类型容错 + 范围/顺序校验。

- 类型容错: int / 浮点整数 / "7" / "07:00" 救得回; null / 纯文字丢弃该块, 不崩;
- 范围/顺序: 0 <= start < end <= 24, 倒置块、超范围块丢弃;
- 缺键丢弃: 不再 .get("start", 8) 静默编时间, 宁可少一块不造一块;
- 全坏: 返回空列表, 整条链路 (make_daily_plan → NPC) 零入库不崩。
无网络: 子类化 RealLLM 覆写 _chat_json 直接喂坏输出。
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from persona_agent import NPC
from persona_agent.llm_real import RealLLM
from tests.test_persistence import _StubLLM, TRAITS


def _llm_with(data) -> RealLLM:
    """RealLLM 子类: _chat_json 直接回给定数据, 不发网络请求。"""
    class FedLLM(RealLLM):
        def _chat_json(self, system, user, **kw):
            return data
    return FedLLM()


def test_string_hours_rescued():
    """"07:00" / "9" / 7.0 都救得回来。"""
    out = _llm_with([
        {"start": "07:00", "end": "9", "activity": "起床"},
        {"start": 7.0, "end": 8, "activity": "晨间"},
    ]).generate_plan({"social": 0.7}, "", "第一天")
    assert out == [(7, 9, "起床"), (7, 8, "晨间")]


def test_bad_entries_dropped_not_crash():
    """null / 纯文字 / 非 dict 元素: 丢弃该块, 不抛异常。"""
    out = _llm_with([
        {"start": None, "end": 9, "activity": "null start"},
        {"start": "早上", "end": 9, "activity": "文字 start"},
        "不是字典",
        {"start": 9, "end": 12, "activity": "合法"},
    ]).generate_plan({"social": 0.7}, "", "第一天")
    assert out == [(9, 12, "合法")]


def test_inverted_and_outrange_dropped():
    """倒置块 (9-7) 和超范围块 (25-30) 丢弃, 合法块保留。"""
    out = _llm_with([
        {"start": 9, "end": 7, "activity": "倒着走"},
        {"start": 25, "end": 30, "activity": "半夜排计划"},
        {"start": 9, "end": 12, "activity": "合法"},
    ]).generate_plan({"social": 0.7}, "", "第一天")
    assert out == [(9, 12, "合法")]


def test_missing_key_dropped_not_fabricated():
    """缺 start 不再默认 8 点 (旧行为会编出 08-12 假块), 直接丢弃。"""
    out = _llm_with([
        {"end": 12, "activity": "缺 start"},
        {"start": 9, "activity": "缺 end"},
    ]).generate_plan({"social": 0.7}, "", "第一天")
    assert out == []


def test_all_bad_returns_empty():
    """全坏输出: 空列表, 不崩。"""
    assert _llm_with([{"start": "早上", "end": "晚上"}]
                     ).generate_plan({"social": 0.7}, "", "第一天") == []
    assert _llm_with({"start": 9, "end": 12, "activity": "不是列表"}
                     ).generate_plan({"social": 0.7}, "", "第一天") == []


def test_decompose_subtasks_confined_to_parent():
    """子任务必须落在父块 (9,12) 内: 漂回 8 点 (7-9) 的丢弃。"""
    out = _llm_with([
        {"start": 7, "end": 9, "subtask": "漂到父块外"},
        {"start": 9, "end": 10, "subtask": "构思"},
        {"start": 11, "end": 14, "subtask": "超出父块"},
    ]).decompose_activity("备货咖啡豆", 9, 12)
    assert out == [(9, 10, "构思")]


def test_make_daily_plan_clamps_subtasks_to_parent(tmp_path):
    """E15: make_daily_plan 把越出父块的子任务 clamp 到 [start,end] (整段在外丢弃)。
    用自定义 LLM 的 decompose_activity 直接回越界子任务 (绕过 RealLLM 的 parse 层
    drop), 验证计划层有独立的 clamp 兜底 (防御纵深, 不依赖 LLM 后端的 parse)。
    _StubLLM.generate_plan 回 [(7,9,"stub-activity")] 这个 2 小时块 (会被分解)。"""
    class OverRangeLLM(_StubLLM):
        def decompose_activity(self, activity, start, end):
            # 三个子任务: 整段在父块前 (丢弃) / 越出父块尾 (clamp 到父块尾) / 正常
            return [(start - 2, start - 1, "块前"),
                    (end - 1, end + 2, "越尾"),
                    (start, start + 1, "正常")]
    npc = NPC.create("Klaus", dict(TRAITS), llm=OverRangeLLM(), data_dir=str(tmp_path))
    npc.generate_daily_plan(previous_day="", date="第一天", now=7.0)
    plans = [m.content for m in npc.store.all_valid(types=["plan"])]
    assert "07-09 stub-activity" in plans, "父块本身应入库"
    assert "08-09 越尾" in plans, \
        f"越出父块尾的子任务应 clamp 到父块尾 08-09, 实际: {plans}"
    assert "07-08 正常" in plans, "父块内的子任务原样保留"
    assert not any("块前" in p for p in plans), "整段在父块前的子任务应丢弃"


class _BadBlocksLLM(_StubLLM):
    """回混合非法块 (越界/倒置) + 合法块, 验证 PlanningEngine 自身校验。"""
    def __init__(self, blocks):
        super().__init__()
        self._blocks = blocks
    def generate_plan(self, persona_traits, previous_day, date, context=""):
        return list(self._blocks)


def test_make_daily_plan_drops_invalid_top_blocks(tmp_path):
    """审查#2: make_daily_plan 顶层块过合法性闸 —— 越界 (25-26)/倒置 (10-9) 丢弃,
    合法块保留。PlanningEngine 自己的兜底, 不依赖 RealLLM parse (stub 绕过它)。"""
    llm = _BadBlocksLLM([(25, 26, "越界"), (10, 9, "倒置"), (7, 9, "合法")])
    npc = NPC.create("Klaus", dict(TRAITS), llm=llm, data_dir=str(tmp_path))
    ids = npc.generate_daily_plan(previous_day="", date="第一天", now=7.0)
    plans = [m.content for m in npc.store.all_valid(types=["plan"])]
    assert any(p.startswith("07-09 合法") for p in plans), "合法块应入库"
    assert not any("越界" in p for p in plans), "越界块 (25-26) 应丢弃"
    assert not any("倒置" in p for p in plans), "倒置块 (10-9) 应丢弃"


def test_replan_drops_cross_day_and_past_blocks(tmp_path):
    """审查#3: replan_from_now 先校验合法性再 anchor 裁剪 —— 跨日块 (23-25) 被校验
    丢 (end<=24), 过去块 (21-22) 被 anchor 丢, 合法块 (22-23) 保留。"""
    llm = _BadBlocksLLM([(23, 25, "跨日"), (21, 22, "过去"), (22, 23, "合法")])
    npc = NPC.create("Klaus", dict(TRAITS), llm=llm, data_dir=str(tmp_path))
    ids, blocks = npc.planner.replan_from_now(
        npc.store, npc.persona_traits, now=22.0, interruption="x")
    assert blocks == [(22, 23, "合法")], \
        f"跨日/过去块应丢, 只留合法块, 实际 {blocks}"


def test_all_bad_plan_empty_store(tmp_path):
    """集成: 全坏计划 → make_daily_plan 零入库, NPC 无计划块 (诚实的"没计划")。"""
    class NoPlanLLM(_StubLLM):
        def generate_plan(self, persona_traits, previous_day, date, context=""):
            return []
    npc = NPC.create("NoPlan", dict(TRAITS), llm=NoPlanLLM(), data_dir=str(tmp_path))
    ids = npc.generate_daily_plan(previous_day="", date="第一天", now=7.0)
    assert ids == []
    assert npc.store.all_valid(types=["plan"]) == []
    assert npc._plan_blocks == []
    assert npc._current_activity(9.5) == ""
