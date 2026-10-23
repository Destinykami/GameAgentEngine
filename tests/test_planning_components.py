"""规划组件的窄接口、失败顺序和状态恢复契约。"""

from dataclasses import replace

import pytest

from game_agent.cognition.planning import PlanningEngine, PlanState
from game_agent.memory.models import MemoryRecord


class PlanMemory:
    """只提供规划需要的三个记忆方法，无数据库或向量接口。"""

    def __init__(self):
        self.records = [MemoryRecord(
            content="旧计划", timestamp=0.0, type="plan", id=1)]
        self.events = []

    def all_valid(self, *, types=None, shared=False):
        self.events.append(("read", types, shared))
        return [replace(record) for record in self.records
                if record.valid and (types is None or record.type in types)
                and (not shared or record.player_id is None)]

    def add(self, rec):
        rec.id = len(self.records) + 1
        self.records.append(rec)
        self.events.append(("add", rec.content))
        return rec.id

    def invalidate(self, mem_id):
        self.records[mem_id - 1].valid = False
        self.events.append(("invalidate", mem_id))


def test_generation_uses_ports_and_retires_old_plans_after_new_writes():
    memory = PlanMemory()

    class Model:
        def generate_plan(self, persona_traits, previous_day, date, context=""):
            memory.events.append(("generate", context))
            return [(7, 10, "工作"), (10, 11, "会面")]

        def decompose_activity(self, activity, start, end):
            memory.events.append(("decompose", activity))
            return [(-4, 8, "准备"), (8, 13, "收尾"), (7, 10, "工作")]

    planner = PlanningEngine(Model())
    ids, blocks = planner.make_daily_plan(memory, {}, "昨天", "今天", 7.0,
                                          context="世界背景")
    assert ids == [2, 5]  # 返回顶层 id，子任务仍单独入库。
    assert blocks == [(7, 10, "工作"), (10, 11, "会面")]
    assert [record.content for record in memory.records[1:]] == [
        "07-10 工作", "07-08 准备", "08-10 收尾", "10-11 会面"]
    assert memory.events[0] == ("generate", "世界背景")
    assert memory.events[-1] == ("invalidate", 1)
    assert sum(event[0] == "decompose" for event in memory.events) == 1
    assert planner.daily_plan_count == 1
    assert all(record.importance == 4.0 for record in memory.records[1:])


def test_failed_decomposition_retains_partial_memory_and_previous_npc_state():
    from game_agent import NPC

    class Model:
        def generate_plan(self, persona_traits, previous_day, date, context=""):
            return [(7, 10, "新计划")]

        def decompose_activity(self, activity, start, end):
            raise RuntimeError("decomposition failed")

    memory = PlanMemory()
    npc = NPC("测试人", {}, llm=Model(), store=memory)
    npc.plan_state.replace([(1, 2, "旧活动")], interruption="旧中断")
    with pytest.raises(RuntimeError, match="decomposition failed"):
        npc.generate_daily_plan("昨天", "今天", 7.0)
    assert npc.plan_state.blocks == [(1, 2, "旧活动")]
    assert npc.plan_state.interruption == "旧中断"
    assert [(record.content, record.valid) for record in memory.records] == [
        ("旧计划", True), ("07-10 新计划", True)]
    assert npc.planner.daily_plan_count == 1


@pytest.mark.parametrize("replan", [False, True])
def test_model_failure_preserves_counter_and_interruption_write_order(replan):
    class Model:
        def generate_plan(self, persona_traits, previous_day, date, context=""):
            raise RuntimeError("generation failed")

    memory = PlanMemory()
    planner = PlanningEngine(Model())
    with pytest.raises(RuntimeError, match="generation failed"):
        if replan:
            planner.replan_from_now(memory, {}, 9.75, "被 Aria 打断",
                                    interruption_player="Aria")
        else:
            planner.make_daily_plan(memory, {}, "昨天", "今天", 7.0)
    assert (planner.daily_plan_count, planner.replan_count) == (0, 0)
    assert memory.records[0].valid
    if replan:
        assert len(memory.records) == 2
        interruption = memory.records[1]
        assert interruption.type == "observation"
        assert interruption.player_id == "Aria"
        assert interruption.importance == 5.0
        assert interruption.content == "计划被打断: 被 Aria 打断"
    else:
        assert len(memory.records) == 1


def test_plan_state_priority_boundaries_and_instance_isolation():
    state = PlanState()
    other = PlanState()
    state.replace([(7, 10, "第一个活动"), (8, 11, "重叠活动")],
                  interruption="中断兜底")
    assert state.context(32.5) == "第一个活动"  # 次日按当天小时查询，不重排重叠块。
    assert state.context(11.0) == "中断兜底"  # 右边界不包含。
    assert state.context(8.0, explicit="") == ""
    assert state.context(8.0, explicit="指定活动") == "指定活动"
    assert other.blocks == [] and other.interruption == ""
    state.replace([])
    assert state.context(8.0) == ""


def test_saved_blocks_preserve_legacy_conversion_and_reset_interruption():
    original = PlanState([(7, 9, "活动")], interruption="不会持久化的中断")
    saved = original.saved_blocks()
    saved.append([9.9, 11.1, 123])
    saved.extend([[True, 2, "旧布尔时间"], ["7", 9, "忽略"], [1], None])
    restored = PlanState.from_saved(saved)
    assert restored.blocks == [(7, 9, "活动"), (9, 11, "123"),
                               (1, 2, "旧布尔时间")]
    assert restored.interruption == ""
    assert original.blocks == [(7, 9, "活动")]
    assert PlanState.from_saved(None).blocks == []
