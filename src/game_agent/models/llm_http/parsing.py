"""纯输出解析与一次 JSON 修复请求，不加载模型客户端。"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

def extract_json(text: str) -> str:
    """从模型输出里抠出 JSON 片段 (容忍 markdown 代码围栏与前后杂字)。"""
    t = text.strip()
    if t.startswith("```"):
        parts = t.split("```")
        t = parts[1] if len(parts) > 1 else t
        if t.startswith("json"):
            t = t[4:]
        t = t.strip()
    for open_c, close_c in (("[", "]"), ("{", "}")):
        s = t.find(open_c)
        e = t.rfind(close_c)
        if s != -1 and e > s:
            return t[s:e + 1]
    return t


def parse_hour(value: Any) -> int | None:
    """从模型输出提取整点小时。容忍 int / 浮点整数 / "7" / "07:00" (取冒号前);
    解析不出 (None、"早上"等纯文字) 返回 None, 由调用方丢弃整块 —— 不抛异常
    (旧实现 int() 直接炸, 一个坏输出崩掉整个 World.step)。"""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        head = value.strip().split(":")[0]
        if head.isdigit():
            return int(head)
    return None


def parse_blocks(items: Any, activity_key: str,
                  lo: int = 0, hi: int = 24) -> list[tuple[int, int, str]]:
    """把模型计划输出解析为合法时间块 (generate_plan / decompose_activity 共用)。

    - 类型容错: "07:00" 这类救得回的救, 救不回的丢弃该块;
    - 范围/顺序: lo <= start < end <= hi, 倒置块、超范围块丢弃;
      日计划边界 (0, 24), 分解子任务边界 = 父块 (start, end);
    - 缺键丢弃: 不再 .get("start", 8) 静默编时间, 宁可少一块不造一块;
    - 全坏返回 [], 调用方按空计划处理 (诚实: "当前正忙"没有块可报)。
    """
    out: list[tuple[int, int, str]] = []
    if not isinstance(items, list):
        return out
    for item in items:
        if not isinstance(item, dict) or activity_key not in item:
            continue
        s = parse_hour(item.get("start"))
        e = parse_hour(item.get("end"))
        if s is None or e is None:
            continue   # 解析不出 / 缺键: 整块丢弃
        if not (lo <= s < e <= hi):
            continue   # 倒置 / 超范围
        out.append((s, e, str(item[activity_key])))
    return out


def extract_int(raw: str, lo: int, hi: int, default: int = 0) -> int:
    """提取第一个整数并夹到 [lo, hi]; 支持负号; 提不出给 default。"""
    i, n = 0, len(raw)
    while i < n and raw[i] not in "-0123456789":
        i += 1
    if i >= n:
        return default
    sign = 1
    if raw[i] == "-":
        sign = -1
        i += 1
    digits = ""
    while i < n and raw[i].isdigit():
        digits += raw[i]
        i += 1
    if not digits:
        return default
    return max(lo, min(hi, sign * int(digits)))


def request_json(request: Callable[..., str], system: str, user: str, *, think: bool = False,
               temperature: float = 0.0, max_tokens: int = 2048,
               _stats_tag: str = "unspecified") -> Any:
    """请求模型返回严格 JSON 并解析; 解析失败则重试一次。"""
    raw = request(system, user, think=think, temperature=temperature,
                     max_tokens=max_tokens, _stats_tag=_stats_tag)
    try:
        return json.loads(extract_json(raw))
    except json.JSONDecodeError:
        retry = request(system, user + "\n\n只输出 JSON, 不要任何其他文字。",
                           think=think, temperature=0.0, max_tokens=max_tokens,
                           _stats_tag=_stats_tag)
        return json.loads(extract_json(retry))
