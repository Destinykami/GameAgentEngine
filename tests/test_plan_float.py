"""计划块归一化/校验返回回归 (F5-3)。

非整数浮点块不得让 f"{start:02d}" 打崩; make_daily_plan 返回给 NPC._plan_blocks
的必须是真正入库的校验后块。
"""

from __future__ import annotations



from game_agent import NPC
from tests.test_persistence import _StubLLM, TRAITS


class _FloatPlan(_StubLLM):
    def generate_plan(self, persona_traits, previous_day, date, context=""):
        return [(7.5, 9.5, "半日浮点"), (7.0, 9.0, "正常")]


def test_float_plan_blocks_are_dropped_not_crash(tmp_path):
    npc = NPC.create("T", dict(TRAITS), llm=_FloatPlan(),
                     data_dir=str(tmp_path))
    ids = npc.generate_daily_plan(previous_day="", date="d", now=8.0)
    plans = [m.content for m in npc.store.all_valid(types=["plan"])]
    assert any(p.startswith("07-09 正常") for p in plans), "整数值浮点应接受"
    assert not any("半日浮点" in p for p in plans), "7.5/9.5 应丢弃, 不静默取整"
    assert npc._plan_blocks == [(7, 9, "正常")], \
        "返回给 react 的必须是校验后的块"


class _FloatSub(_StubLLM):
    def generate_plan(self, persona_traits, previous_day, date, context=""):
        return [(7, 11, "大块")]

    def decompose_activity(self, activity, start, end):
        return [(7.0, 9.0, "子任务"), (7.5, 8.5, "坏子任务")]


def test_float_subtasks_are_normalized_or_dropped(tmp_path):
    npc = NPC.create("T2", dict(TRAITS), llm=_FloatSub(),
                     data_dir=str(tmp_path))
    npc.generate_daily_plan(previous_day="", date="d", now=8.0)
    plans = [m.content for m in npc.store.all_valid(types=["plan"])]
    assert any("07-09 子任务" in p for p in plans)
    assert not any("坏子任务" in p for p in plans)
