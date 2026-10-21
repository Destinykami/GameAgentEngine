"""forgetting: 遗忘/衰减演示 (真实 LLM)。

演示记忆随游戏时间**部分衰减降权** (不删除):
  1. 种入记忆: Aria 的帮助 (被反思固化 → 受保护) + 两条无引用的世界杂事
  2. 时间跳跃 ~8 天, 触发遗忘清扫 (降权)
  3. 对比 importance 降权前后: 固化进反思的关系记忆 importance 不变,
     原始杂事降到下限 MIN_IMPORTANCE 但保留, 反思降权但留存; 记忆总数不删。

尺度说明: 原始观察半衰期 ~2 天 (48h), 反思/情节摘要 ~1 周 (168h),
身份信念 ~2 周 (336h), 计划 ~1 天 (24h)。降到下限即止, 不删除。

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


def _dump(npc: NPC, help_id: int) -> None:
    for m in sorted(npc.store.all_valid(), key=lambda r: r.timestamp):
        tag = "  ★固化(受保护)" if m.id == help_id else ""
        print(f"  #{m.id:2d} [{m.type:11s}] imp={m.importance:4.1f} "
              f"t={m.timestamp:5.0f} {m.content[:28]}{tag}")


def main() -> int:
    npc = NPC.create("Mira", {"social": 0.6, "goal_oriented": 0.4},
                     llm=RealLLM(), embedder=make_embedder(),
                     data_dir=DATA_DIR)

    banner("第 0 天 — 种入记忆")
    npc.observe("Mira 在咖啡馆擦拭桌子、整理零钱盒", now=1.0)      # 无引用世界杂事
    help_id = npc.observe("Aria 主动帮 Mira 搬货并修好了咖啡机", now=2.0,
                          player_id="Aria")
    npc.reflect_relationship("Aria", now=3.0)   # 关系记忆固化为反思 (引用 help_id)
    npc.observe("Mira 给橱窗换了新的装饰贴纸", now=4.0)            # 无引用世界杂事
    count0 = npc.memory_count()
    print(f"记忆总数: {count0}   对Aria信任度: {npc.trust_toward('Aria'):+.2f}")
    print("\n降权前 importance:")
    _dump(npc, help_id)
    npc.save()

    banner("第 8 天 — 时间跳跃, 触发遗忘清扫 (降权, 不删除)")
    down_ids = npc.forget(200.0)
    count1 = npc.memory_count()
    print(f"记忆总数: {count0} → {count1}  (降权 {len(down_ids)} 条, 无删除)")
    print(f"对Aria信任度: {npc.trust_toward('Aria'):+.2f}  "
          f"(帮助记忆受保护且未删除, 信任不回归 0)")
    print("\n降权后 importance (★=受保护不变, ↓=被降权):")
    for m in sorted(npc.store.all_valid(), key=lambda r: r.timestamp):
        tag = "  ★固化(受保护)" if m.id == help_id else ""
        mark = "↓" if m.id in down_ids else " "
        print(f"  {mark} #{m.id:2d} [{m.type:11s}] imp={m.importance:4.1f} "
              f"t={m.timestamp:5.0f} {m.content[:28]}{tag}")
    # 再种一条近期记忆, 展示"新事不会被降权"
    npc.observe("一周过去, 店里一切如常", now=200.0)
    npc.store.close()
    print("\n完成: 固化进反思的关系记忆 importance 不变, 未固化的原始杂事降到"
          "下限但保留 (不删除), 反思降权但留存 —— 这是降权不是抹除。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
