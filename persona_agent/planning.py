"""规划引擎: 层次化规划 (日计划 → 小时 → 分钟) + 反应后的重规划。

- 日计划结合人格、近期经历摘要、前一天活动生成 5-8 个时间块。
- 逐层递归分解, 而非一次性生成全天 288 个动作 (降低单次复杂度, 保证高层一致)。
- 计划作为 'plan' 记忆存入记忆流, 参与后续检索, 保持行为时间一致性。
- 反应发生后, 从当前时刻起重规划后续。
"""

from __future__ import annotations

import math
from typing import Sequence

from .llm import LLMClient
from .memory import MemoryRecord, MemoryStore


class PlanningEngine:
    def __init__(self, llm: LLMClient) -> None:
        self._llm = llm

    # ------------------------------------------------------------- 日计划
    def make_daily_plan(self, store: MemoryStore, persona_traits: dict,
                        previous_day: str, date: str, now: float,
                        context: str = "") -> tuple[list[int], list[tuple[int, int, str]]]:
        """生成日计划并逐层分解, 全部存为 plan 记忆, 返回 (顶层计划 id, 顶层块)。

        context 是 NPC 近期记忆/世界事件, 让世界背景驱动计划 (而非只靠人格)。
        顶层块 (start, end, activity) 一并返回, 供调用方判断"当前正忙"——
        计划只存进记忆流是不够的: 反应决策不走检索, 需要直接拿到块。
        """
        top_blocks = self._llm.generate_plan(persona_traits, previous_day, date, context)
        # M4: 新的一天计划**替换**旧的 —— 计划是前瞻性的, 跨日后昨日计划 (含分解
        # 出的子任务) 纯属垃圾, 直接失效而非降权到地板留在流里: 30 天模拟会积
        # 数百条旧计划污染小库检索。观察性记忆才"降权不删", 计划不是经历。
        # 今日计划为空 (LLM 返回空, M3 空计划) 时也照旧失效 —— 新的一天开始了,
        # 昨天的安排已不再是"现在正在做的事"。
        old_ids = [m.id for m in store.all_valid(types=["plan"])]
        top_ids: list[int] = []
        for start, end, activity in top_blocks:
            top_id = self._save_plan(store, now, f"{start:02d}-{end:02d} {activity}",
                                     player_id=None)
            top_ids.append(top_id)
            # 只对多于一小时的块分解为小时级子任务; 1 小时块已是最细粒度, 分解会
            # 把原活动原样回声成"子任务"造成重复, 故跳过。
            if end - start > 1:
                for s, e, sub in self._llm.decompose_activity(activity, start, end):
                    sub_content = f"{s:02d}-{e:02d} {sub}"
                    if sub_content == f"{start:02d}-{end:02d} {activity}":
                        continue   # 保险: 子任务与顶层块完全相同则跳过
                    self._save_plan(store, now, sub_content, player_id=None)
        for old_id in old_ids:
            store.invalidate(old_id)
        return top_ids, top_blocks

    # ------------------------------------------------------------- 重规划
    def replan_from_now(self, store: MemoryStore, persona_traits: dict,
                        now: float, interruption: str) -> tuple[list[int], list[tuple[int, int, str]]]:
        """从当前时刻起重规划: 记下中断原因, 只生成当前时刻之后的计划, 返回 (计划 id, 块)。

        锚定当前时刻 (LLM 尽力 + 规则兜底, 同框架"LLM 战略 + 规则执行"分工):
        - context 告知 LLM 当前时刻, 只要求生成剩余时间的块;
        - 规则层再 clamp: 整块在过去的丢弃, 跨越锚点的块起点抬到锚点 (小时粒度)。
          LLM 不听话 (回全天计划) 也会被裁掉过去的部分, 保证"从当前时刻起"。
        旧计划失效: 重规划前把库里所有有效 plan 记忆标记失效 —— 新计划取代旧计划,
        新旧不应同流共存 (否则检索把过期计划当当前安排)。日计划的跨日清理另见 M4。
        """
        # 记录中断事件为一条观察
        self._save_obs(store, now, f"计划被打断: {interruption}")
        hour = now % 24
        context = (f"计划在 {int(hour):02d}:{int((hour % 1) * 60):02d} 被打断, "
                   f"只生成从当前时刻到当天结束的计划, 不要重排已经过去的时间。")
        blocks = self._llm.generate_plan(persona_traits, "", "replan", context=context)
        # 规则层锚定: 锚点 = 下一个整点 (当前小时内的剩余不足 1 小时, 不排块)
        anchor = math.ceil(hour - 1e-9)
        clamped: list[tuple[int, int, str]] = []
        for start, end, activity in blocks:
            if end <= anchor:
                continue   # 整块在过去
            if start < anchor:
                start = anchor   # 跨越锚点: 只保留锚点之后的部分
            clamped.append((start, end, activity))
        # 旧计划失效 (先收集再存新块, 别把刚存的新块也失效了)
        old_ids = [m.id for m in store.all_valid(types=["plan"])]
        ids: list[int] = []
        for start, end, activity in clamped:
            ids.append(self._save_plan(store, now,
                                       f"[重规划]{start:02d}-{end:02d} {activity}",
                                       player_id=None))
        for old_id in old_ids:
            store.invalidate(old_id)
        return ids, clamped

    # --------------------------------------------------------------- 内部
    @staticmethod
    def _save_plan(store: MemoryStore, now: float, content: str,
                   player_id: str | None) -> int:
        return store.add(MemoryRecord(content=content, timestamp=now,
                                      type="plan", player_id=player_id,
                                      importance=4.0))

    @staticmethod
    def _save_obs(store: MemoryStore, now: float, content: str,
                  player_id: str | None = None) -> int:
        return store.add(MemoryRecord(content=content, timestamp=now,
                                      type="observation", player_id=player_id,
                                      importance=5.0))
