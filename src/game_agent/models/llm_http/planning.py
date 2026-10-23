"""原任务提示词及结果转换；只依赖传入的请求能力。"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Sequence

from .parsing import parse_blocks

def generate_plan(request: Callable[..., Any], persona_traits: dict[str, float],
                  previous_day: str, date: str,
                  context: str = "") -> list[tuple[int, int, str]]:
    ctx_line = ("该 NPC 近期的记忆与所处世界: " + context + "\n") if context else ""
    user = ("为一个 NPC 生成 " + date + " 的一天计划。人格特质: "
            + str(persona_traits) + "。\n" + ctx_line
            + "前一天活动: " + (previous_day or "(无)")
            + "\n结合上述世界背景与人格, 生成 5 到 8 个时间块。"
              "若世界正处于紧张/危机 (如迫害、搜捕、禁令), 计划应体现谨慎与应对 "
              "(避开危险地、低调、检查藏匿处、准备应变); 若世界平静, 才是寻常日子。"
              "输出 JSON 数组, "
              '例如 [{"start": 7, "end": 9, "activity": "起床"}]。')
    data = request("你是一个日程规划器。", user,
                           think=False, temperature=0.3,
                           _stats_tag="generate_plan")
    # 类型容错 + 范围/顺序校验 (0 <= start < end <= 24), 坏块丢弃不崩
    return parse_blocks(data, "activity", 0, 24)


def decompose_activity(request: Callable[..., Any], activity: str, start: int, end: int) -> \
        list[tuple[int, int, str]]:
    user = ("把活动 '" + activity + "' 从 " + f"{start:02d}" + ":00 到 "
            + f"{end:02d}" + ":00 分解为小时级子任务。\n"
            '输出 JSON 数组, 例如 [{"start": 13, "end": 14, "subtask": "构思"}]。')
    data = request("你是一个任务分解器。", user,
                           think=False, temperature=0.0,
                           _stats_tag="decompose_activity")
    # 子任务时间必须落在父块 (start, end) 内: 模型常漂回默认 8 点, 越界即丢
    return parse_blocks(data, "subtask", start, end)
