"""重规划锚定测试 (H4 回归): replan_from_now 只生成当前时刻之后的块, 并失效旧计划。

- 锚定: 整块在过去的丢弃; 跨越锚点的块起点抬到锚点 (小时粒度)。
  LLM 回全天计划 (不听话) 也会被规则层裁掉过去的部分。
- 失效: 重规划前所有有效 plan 记忆被标记失效, 新旧计划不同流共存。
无网络, stub LLM。
"""

from __future__ import annotations



from game_agent import NPC
from tests.test_persistence import _StubLLM, TRAITS

DAY_BLOCKS = [(7, 9, "起床整理"), (9, 12, "备货咖啡豆"), (12, 13, "午餐")]


class ReplanStubLLM(_StubLLM):
    """日计划与重规划都回全天块 —— 故意不听话, 验证规则层兜底。"""

    def generate_plan(self, persona_traits, previous_day, date, context=""):
        return list(DAY_BLOCKS)


def _make(tmp_path) -> NPC:
    return NPC.create("Replan", dict(TRAITS), llm=ReplanStubLLM(),
                      data_dir=str(tmp_path))


def _plans(npc, valid: bool = True):
    if valid:
        return [m.content for m in npc.store.all_valid(types=["plan"])]
    return [m.content for m in npc.store.all_invalid()]


def test_replan_drops_past_blocks(tmp_path):
    """LLM 回全天计划, 规则层裁掉锚点 (10 点) 之前的块。"""
    npc = _make(tmp_path)
    ids, blocks = npc.planner.replan_from_now(
        npc.store, npc.persona_traits, now=9.75, interruption="Aria 的派对邀请")
    # 锚点 = 10 (9.75 向上取整): 07-09 整块丢弃, 09-12 起点抬到 10
    assert blocks == [(10, 12, "备货咖啡豆"), (12, 13, "午餐")], \
        f"重规划块应锚定在 10 点之后, 实际 {blocks}"
    valid = _plans(npc)
    assert valid == ["[重规划]10-12 备货咖啡豆", "[重规划]12-13 午餐"], \
        f"入库块应只含锚点之后的计划, 实际 {valid}"


def test_replan_invalidates_old_plans(tmp_path):
    """日计划已入库后重规划: 旧计划 (含分解子任务) 全部失效, 不残留。"""
    npc = _make(tmp_path)
    npc.generate_daily_plan(previous_day="", date="第一天", now=7.0)
    before = _plans(npc)
    assert before, "日计划应已入库"
    npc.replan(now=9.75, interruption="Aria 的派对邀请")
    valid = _plans(npc)
    invalid = _plans(npc, valid=False)
    for content in before:
        assert content not in valid, f"旧计划 {content} 应失效, 仍有效"
        assert content in invalid, f"旧计划 {content} 应在失效区"
    assert all(c.startswith("[重规划]") for c in valid), "有效的只剩新重规划块"


def test_replan_late_night_no_blocks(tmp_path):
    """深夜重规划 (锚点 24 点): 无块可排, 不入库任何计划。"""
    npc = _make(tmp_path)
    ids, blocks = npc.planner.replan_from_now(
        npc.store, npc.persona_traits, now=23.6, interruption="处理火灾")
    assert blocks == [] and ids == []
    assert _plans(npc) == []


def test_replan_anchor_exact_hour_keeps_block(tmp_path):
    """整点重规划 (锚点 = 当前整点): 从该整点开始的块原样保留。"""
    npc = _make(tmp_path)
    ids, blocks = npc.planner.replan_from_now(
        npc.store, npc.persona_traits, now=9.0, interruption="Bram 的委托")
    assert (9, 12, "备货咖啡豆") in blocks, "整点锚定不应误伤从该整点开始的块"
    assert (7, 9, "起床整理") not in blocks


class CaptureContextLLM(_StubLLM):
    """记录 generate_plan 每次收到的 context (验证重规划是否带世界背景)。"""

    def __init__(self) -> None:
        super().__init__()
        self.contexts: list[str] = []

    def generate_plan(self, persona_traits, previous_day, date, context=""):
        self.contexts.append(context)
        return list(DAY_BLOCKS)


def test_replan_context_includes_world_background(tmp_path):
    """E14: 重规划也带世界背景 (近期观察) —— 被打断后仍要在眼狩令等背景下重排
    剩余日程, 而非'岁月静好'。context 应同时含世界背景 + 中断锚定指令。"""
    from game_agent import MemoryRecord
    llm = CaptureContextLLM()
    npc = NPC.create("Klaus", dict(TRAITS), llm=llm, data_dir=str(tmp_path))
    npc.store.add(MemoryRecord(content="眼狩令全城生效, 持神之眼者被搜捕",
                               timestamp=1.0, type="observation", importance=9.0))
    npc.generate_daily_plan(previous_day="第0天", date="第1天", now=8.0)
    llm.contexts.clear()
    npc.replan(now=14.0, interruption="被执行官袭击")
    ctx = llm.contexts[-1]
    assert "眼狩令" in ctx, f"世界背景 (近期观察) 应进重规划 context, 实际: {ctx!r}"
    assert "被打断" in ctx, "中断锚定指令应保留"
