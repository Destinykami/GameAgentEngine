"""规划生成编排；时间、记忆及当前计划状态由专门组件负责。"""

from __future__ import annotations

from .contracts import PlanningMemory, PlanningModel
from .memory import active_plan_ids, retire_plans, save_observation, save_plan
from .rules import PlanBlock, daily_hours, next_hour, replan_hours, subtask_hours


class PlanningEngine:
    def __init__(self, llm: PlanningModel) -> None:
        self._llm = llm
        self.daily_plan_count = 0
        self.replan_count = 0

    def make_daily_plan(self, store: PlanningMemory, persona_traits: dict,
                        previous_day: str, date: str, now: float,
                        context: str = "") -> tuple[list[int], list[PlanBlock]]:
        """生成日计划并逐层分解, 全部存为 plan 记忆, 返回 (顶层计划 id, 顶层块)。

        context 是 NPC 近期记忆/世界事件, 让世界背景驱动计划 (而非只靠人格)。
        顶层块 (start, end, activity) 一并返回, 供调用方判断"当前正忙"——
        计划只存进记忆流是不够的: 反应决策不走检索, 需要直接拿到块。
        """
        raw_blocks = self._llm.generate_plan(persona_traits, previous_day, date,
                                             context)
        top_blocks = raw_blocks if isinstance(raw_blocks, list) else []
        self.daily_plan_count += 1   # 每次生成都计 (LLM 返回空计划也花了调用)
        # M4: 新的一天计划**替换**旧的 —— 计划是前瞻性的, 跨日后昨日计划 (含分解
        # 出的子任务) 纯属垃圾, 直接失效而非降权到地板留在流里: 30 天模拟会积
        # 数百条旧计划污染小库检索。观察性记忆才"降权不删", 计划不是经历。
        # 今日计划为空 (LLM 返回空, M3 空计划) 时也照旧失效 —— 新的一天开始了,
        # 昨天的安排已不再是"现在正在做的事"。
        old_ids = active_plan_ids(store)
        top_ids: list[int] = []
        validated: list[PlanBlock] = []
        for start, end, activity in top_blocks:
            hours = daily_hours(start, end)
            if hours is None:
                continue
            start, end = hours
            top_id = save_plan(store, now, f"{start:02d}-{end:02d} {activity}",
                               player_id=None)
            top_ids.append(top_id)
            validated.append((start, end, activity))
            # 只对多于一小时的块分解为小时级子任务; 1 小时块已是最细粒度, 分解会
            # 把原活动原样回声成"子任务"造成重复, 故跳过。
            if end - start > 1:
                subs = self._llm.decompose_activity(activity, start, end)
                for s, e, sub in (subs if isinstance(subs, list) else []):
                    # 子任务只归一化并裁到父块，不额外应用顶层日界过滤。
                    hours = subtask_hours(s, e, start, end)
                    if hours is None:
                        continue
                    s2, e2 = hours
                    sub_content = f"{s2:02d}-{e2:02d} {sub}"
                    # L3: 回声防护是双保险。主防护是上面的"跳过 1 小时块" (回声主
                    # 来源); 这里精确相等只拦"原样回声"的漏网, LLM 换措辞的近重复
                    # 会漏过, 后果是多一条近重复子任务 (轻微冗余, 非正确性问题)。
                    # 不为这种 cosmetic 去重引入语义比较的嵌入成本, 留作兜底即可。
                    if sub_content == f"{start:02d}-{end:02d} {activity}":
                        continue
                    save_plan(store, now, sub_content, player_id=None)
        retire_plans(store, old_ids)
        # F5-3: 返回**校验后**的块, 不再把原始 LLM 块交给 NPC.plan_state.blocks
        # (旧实现会把越界/倒置/浮点块塞进 react 的"当前正忙"上下文)。
        return top_ids, validated

    def replan_from_now(self, store: PlanningMemory, persona_traits: dict,
                        now: float, interruption: str,
                        context: str = "",
                        interruption_player: str | None = None) -> tuple[list[int], list[PlanBlock]]:
        """从当前时刻起重规划: 记下中断原因, 只生成当前时刻之后的计划, 返回 (计划 id, 块)。

        锚定当前时刻 (LLM 尽力 + 规则兜底, 同框架"LLM 战略 + 规则执行"分工):
        - context 告知 LLM 当前时刻, 只要求生成剩余时间的块;
        - 规则层再 clamp: 整块在过去的丢弃, 跨越锚点的块起点抬到锚点 (小时粒度)。
          LLM 不听话 (回全天计划) 也会被裁掉过去的部分, 保证"从当前时刻起"。
        旧计划失效: 新块写入成功后把此前有效 plan 记忆标记失效 —— 新计划取代旧计划,
        新旧不应同流共存 (否则检索把过期计划当当前安排)。日计划的跨日清理另见 M4。

        E14: context 参数携带世界背景 (近期观察), 同 make_daily_plan —— 重规划也要
        在世界背景下生成 (持眼者逢眼狩令, 被打断后仍要规划躲避), 而非"岁月静好"。
        世界背景在前, 中断锚定指令在后。
        """
        # 记录中断事件为一条观察。来源是某个玩家/实体时写进该实体的关系面,
        # 避免"被 Aria 攻击了"进入共享流被其他玩家检索 (面泄漏)。
        save_observation(store, now, f"计划被打断: {interruption}",
                         player_id=interruption_player)
        hour = now % 24
        anchor_ctx = (f"计划在 {int(hour):02d}:{int((hour % 1) * 60):02d} 被打断, "
                      f"只生成从当前时刻到当天结束的计划, 不要重排已经过去的时间。")
        context = f"{context} {anchor_ctx}".strip() if context else anchor_ctx
        raw_blocks = self._llm.generate_plan(persona_traits, "", "replan",
                                             context=context)
        blocks = raw_blocks if isinstance(raw_blocks, list) else []
        self.replan_count += 1
        # 规则层锚定: 锚点 = 下一个整点 (当前小时内的剩余不足 1 小时, 不排块)
        anchor = next_hour(hour)
        clamped: list[PlanBlock] = []
        for start, end, activity in blocks:
            hours = replan_hours(start, end, anchor)
            if hours is None:
                continue
            start, end = hours
            clamped.append((start, end, activity))
        # 旧计划失效 (先收集再存新块, 别把刚存的新块也失效了)
        old_ids = active_plan_ids(store)
        ids: list[int] = []
        for start, end, activity in clamped:
            ids.append(save_plan(store, now,
                                 f"[重规划]{start:02d}-{end:02d} {activity}",
                                 player_id=None))
        retire_plans(store, old_ids)
        return ids, clamped
