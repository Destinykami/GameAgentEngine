"""规划引擎: 层次化规划 (日计划 → 小时 → 分钟) + 反应后的重规划。

- 日计划结合人格、近期经历摘要、前一天活动生成 5-8 个时间块。
- 逐层递归分解, 而非一次性生成全天 288 个动作 (降低单次复杂度, 保证高层一致)。
- 计划作为 'plan' 记忆存入记忆流, 参与后续检索, 保持行为时间一致性。
- 反应发生后, 从当前时刻起重规划后续。
"""

from __future__ import annotations

from typing import Sequence

from .llm import LLMClient
from .memory import MemoryRecord, MemoryStore


class PlanningEngine:
    def __init__(self, llm: LLMClient) -> None:
        self._llm = llm

    # ------------------------------------------------------------- 日计划
    def make_daily_plan(self, store: MemoryStore, persona_traits: dict,
                        previous_day: str, date: str, now: float,
                        context: str = "") -> list[int]:
        """生成日计划并逐层分解, 全部存为 plan 记忆, 返回顶层计划 id。

        context 是 NPC 近期记忆/世界事件, 让世界背景驱动计划 (而非只靠人格)。
        """
        top_blocks = self._llm.generate_plan(persona_traits, previous_day, date, context)
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
        return top_ids

    # ------------------------------------------------------------- 重规划
    def replan_from_now(self, store: MemoryStore, persona_traits: dict,
                        now: float, interruption: str) -> list[int]:
        """从当前时刻起重规划: 记下中断原因, 重新生成后续计划。"""
        # 记录中断事件为一条观察
        self._save_obs(store, now, f"计划被打断: {interruption}")
        # 重新生成剩余时间的计划 (Mock: 以 now 为起点生成简化日计划)
        blocks = self._llm.generate_plan(persona_traits, "", "replan")
        ids: list[int] = []
        for start, end, activity in blocks:
            ids.append(self._save_plan(store, now,
                                       f"[重规划]{start:02d}-{end:02d} {activity}",
                                       player_id=None))
        return ids

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
