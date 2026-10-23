"""规划时间规则；不访问模型、记忆或运行时状态。"""

from __future__ import annotations

import math
from typing import TypeAlias

PlanBlock: TypeAlias = tuple[int, int, str]


def as_hour(value) -> int | None:
    """把 LLM 返回的时间归一化为整点; 非整数浮点/字符串返回 None。

    RealLLM 的 _parse_hour 已在 parse 层做类型容错, 但 stub/自定义 LLM 会
    绕过它。这里统一收口: int、整数值 float (7.0) 接受; 7.5/''/'早上' 丢弃,
    不静默取整 (避免把 7.5-9.5 悄悄挪成别的时段)。bool 是 int 子类, 排除。
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return None


def valid_block(start, end) -> bool:
    """计划块合法性: 0 <= start < end <= 24 (一日时间界 + 顺序不倒置)。

    PlanningEngine 自己的兜底 (防御纵深): RealLLM 的 parse 层也过滤非法块,
    但 stub/自定义 LLM 绕过 parse —— 越界块 (25-26)、倒置块 (10-9) 不得作为
    有效计划进记忆流。调用方应先用 as_hour 归一化。
    """
    return 0 <= start < end <= 24


def daily_hours(start, end) -> tuple[int, int] | None:
    start, end = as_hour(start), as_hour(end)
    if start is None or end is None or not valid_block(start, end):
        return None
    return start, end


def subtask_hours(start, end, parent_start: int,
                  parent_end: int) -> tuple[int, int] | None:
    start, end = as_hour(start), as_hour(end)
    if start is None or end is None:
        return None
    start, end = max(start, parent_start), min(end, parent_end)
    if end <= start:
        return None
    return start, end


def next_hour(hour: float) -> int:
    return math.ceil(hour - 1e-9)


def replan_hours(start, end, anchor: int) -> tuple[int, int] | None:
    normalized = daily_hours(start, end)
    if normalized is None:
        return None
    start, end = normalized
    if end <= anchor:
        return None
    if start < anchor:
        start = anchor
    if start >= end:
        return None
    return start, end
