"""forgetting: 遗忘/衰减演示 (真实 LLM)。

演示记忆随游戏时间自然衰减:
  1. 种入记忆: Aria 的帮助 (被反思固化 → 受保护) + 两条无引用的世界杂事
  2. 时间跳跃 ~8 天, 触发自动遗忘清扫
  3. 对比: 固化进反思的关系记忆留存, 原始杂事淡去; 信任度因帮助受保护而保持

尺度说明: 原始观察半衰期 ~2 天, 反思 ~2 周, 计划 ~1 天。
跳到 ~8 天时, 原始观察已跌破阈值, 反思仍高于阈值 → 正好展示"分层衰减"。

跑法: python examples/forgetting.py   (需 LLM 可达)
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from persona_agent import NPC, RealLLM, make_embedder

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")


def banner(t: str) -> None:
    print("\n" + "═" * 72)
    print(t)
    print("═" * 72)


def main() -> int:
    npc = NPC.create("Mira", {"social": 0.6, "goal_oriented": 0.4},
                     llm=RealLLM(), embedder=make_embedder(),
                     data_dir=DATA_DIR)

    banner("第 0 天 — 种入记忆")
    npc.observe("Mira 在咖啡馆擦拭桌子、整理零钱盒", now=1.0)
    help_id = npc.observe("Aria 主动帮 Mira 搬货并修好了咖啡机", now=2.0,
                          player_id="Aria")
    npc.reflect_relationship("Aria", now=3.0)   # 关系记忆固化为反思 (引用 help_id)
    npc.observe("Mira 给橱窗换了新的装饰贴纸", now=4.0)
    count0 = npc.memory_count()
    print(f"记忆总数: {count0}   对Aria信任度: {npc.trust_toward('Aria'):+.2f}")
    print(f"将被固化的观察 id: {help_id}")
    npc.save()

    banner("第 8 天 — 时间跳跃, 触发遗忘清扫")
    # 显式清扫, 拿到被遗忘的 id 清单 (自动清扫由 SWEEP_INTERVAL 驱动, 见单元测试)
    forgotten_ids = npc.forget(200.0)
    count1 = npc.memory_count()
    print(f"记忆总数: {count0} → {count1}  (被遗忘 {len(forgotten_ids)} 条)")
    print(f"对Aria信任度: {npc.trust_toward('Aria'):+.2f}  "
          f"(帮助记忆受保护, 信任未回归 0)")
    inv = {m.id: m for m in npc.store.all_invalid()}
    print("\n被遗忘的记忆:")
    for i in forgotten_ids:
        m = inv.get(i)
        print(f"  ✗ #{i:2d} [{m.type:11s}] t={m.timestamp:5.0f} {m.content[:32]}")
    # 再种一条近期记忆, 展示"新事不会被遗忘"
    npc.observe("一周过去, 店里一切如常", now=200.0)
    print("\n留存的记忆:")
    for m in sorted(npc.store.all_valid(), key=lambda r: r.timestamp):
        tag = "   ★固化(受保护)" if m.id == help_id else ""
        print(f"  ✓ #{m.id:2d} [{m.type:11s}] t={m.timestamp:5.0f} "
              f"{m.content[:32]}{tag}")
    npc.store.close()
    print("\n完成: 固化进反思的关系记忆留存, 未固化的原始杂事随时间淡去。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
