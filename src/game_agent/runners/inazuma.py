"""稻妻自治运行入口；不在导入时组装世界或连接模型。"""

import os

from ..models.llm_http import RealLLM
from ..models.embeddings_http import make_embedder
from ..world.runtime import World
from ..scenarios.inazuma.definition import (DAYS, MOMENTS, LOCATIONS,
                                            REASON_CAP, TRAVELER_GOAL)
from ..scenarios.inazuma.effects import register_scenario
from ..scenarios.inazuma.setup import populate_world
from ..scenarios.inazuma.outcome import resolve_outcome
from .artifacts import RunPaths, TimelineWriter, reset_directory
from .presentation import banner, status_line, snapshot, timeline_metadata


def run(paths: RunPaths, *, llm_factory=RealLLM, embedder_factory=make_embedder,
        days: int = DAYS, moments=MOMENTS) -> int:
    reset_directory(paths.data_dir)
    w = World("稻妻城", LOCATIONS, path=os.path.join(paths.data_dir, "world.db"))
    writer = None
    try:
        # 证据容量 (引擎通用容量, 非门槛): 限制旅行者持有证据条数, 防记忆无限膨胀。
        w.reason_cap = REASON_CAP
        register_scenario(w)   # 注入稻妻情境的动作效果 (证据生成/锻刀/目击)
        llm = llm_factory()
        emb = embedder_factory()

        populate_world(w, llm, emb, paths.data_dir)

        # 开场世界事件: 眼狩令生效
        w.world_event("雷电将军颁布眼狩令: 全城神之眼一律收缴", now=7.0)
        banner("世界已建, 所有 agent 有各自目标。旅行者目标: " + TRAVELER_GOAL)
        print("初始:", status_line(w))

        shogun = w.get("雷电将军")
        decree_ended = False
        writer = TimelineWriter(paths.live_path, timeline_metadata(w.name))
        # 开场世界事件: 引擎已产出结构化 VisualEvent, 直接序列化 (不再硬编码字符串)。
        opening_ve = [ve.to_dict() for ve in w.visual_events]
        opening_events = [ve.describe() for ve in w.visual_events]
        w.visual_events.clear()
        opening = {"day": 0, "moment": 7.0, "clock": 7.0,
                   "events": opening_events, "visual_events": opening_ve,
                   "states": snapshot(w), "persuade": 0, "decree_ended": False,
                   "shogun_dead": False}
        writer.append(opening)

        for day in range(1, days + 1):
            for moment in moments:
                now = (day - 1) * 24.0 + moment
                banner(f"第 {day} 天 {moment:02.0f}:00  (所有 agent 自治)")
                events, decisions = w.step_autonomous(now)
                for ev in events:
                    print("   " + ev)
                print("   [状态] " + status_line(w))
                note, decree_ended = resolve_outcome(w, llm, decisions, now)
                # 结构化视觉事件 (引擎单一事实源): 本步 execute_action 的事件 +
                # 结局 world_event (若本步触发)。前端回放读它, 不解析中文 events 串。
                visual = [ve.to_dict() for ve in w.visual_events]
                w.visual_events.clear()
                step = {"day": day, "moment": moment, "clock": now,
                        "events": events, "visual_events": visual,
                        "note": note, "states": snapshot(w),
                        "persuade": None, "decree_ended": decree_ended,
                        "shogun_dead": shogun.dead}
                writer.append(step)
                if decree_ended or shogun.dead:
                    break
            if decree_ended or shogun.dead:
                break

        w.save_checkpoint(os.path.join(paths.data_dir, "checkpoints"))
        writer.finish({"decree_ended": decree_ended, "shogun_dead": shogun.dead})

        banner("结局")
        print(status_line(w))
        if decree_ended:
            print(f"\n   眼狩令已废止 (将军{'阵亡' if shogun.dead else '被说服'})。旅行者目标达成。")
        else:
            print(f"\n   {days} 天结束, 眼狩令仍在 (旅程未让将军废止)。将军: 血{shogun.health}, "
                  f"旅行者证据 {len(w.get('旅行者').reasons)} 条。")
        # 存时间线 (供 replay.py 回放)
        tl_path = paths.timeline_path
        writer.write_final(tl_path, timeline_metadata(w.name))
    finally:
        if writer is not None:
            writer.close()
        w.close()
    print(f"\n世界状态已存: {os.path.abspath(paths.data_dir)}/world.db")
    print(f"时间线已存:   {tl_path}  (回放: .venv/bin/python examples/replay.py)")
    return 0
