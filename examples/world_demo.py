"""world_demo: 稻妻城 · 眼狩令 —— 真实游戏世界演示 (真实 LLM)。

5 个 NPC (3 持神之眼: 桃音/刚郎/小梅, 1 执行官, 1 雷电将军) + 脚本驱动旅行者,
跨一天: 旅行者帮持眼者藏匿神之眼, 执行官起疑, 将军疏离旁观。展示:
  - 旅行者对不同 NPC 的差异化信任 (千人千面, 每 NPC 独立的面)
  - 距离驱动的档位切换 (近处 full / 视距内 compressed / 远离 idle)
  - 世界事件 (眼狩令生效 / 执行官搜捕) 的多 NPC 半径感知

世界状态存 data/inazuma/world.db, 每 NPC 独立 data/inazuma/<name>.db。
跑法: python examples/world_demo.py   (需 LLM 可达, 全程真实模型)
"""

from __future__ import annotations

import os
import shutil


from game_agent import World, Location, RealLLM, make_embedder

DATA = os.path.join(os.path.dirname(__file__), "..", "data", "inazuma")

LOCATIONS = [
    Location("稻妻主城", 0, 0),
    Location("治疗堂", 1, 0),
    Location("锻造坊", 2, 0),
    Location("眼狩署", 0, 1),
    Location("神樱庭", 0, 3),
    Location("城外官道", 5, 5),   # 远离全城, 用于演示"玩家离开→全员 idle"
]

NPCS = [
    ("桃音",   {"social": 0.8, "goal_oriented": 0.3}, "治疗堂"),    # 疗愈者, 雷神之眼
    ("刚郎",   {"social": 0.3, "goal_oriented": 0.8}, "锻造坊"),    # 铁匠, 火神之眼
    ("小梅",   {"social": 0.6, "goal_oriented": 0.5}, "稻妻主城"),  # 学者, 风神之眼
    ("执行官", {"social": 0.2, "goal_oriented": 0.7}, "眼狩署"),    # 眼狩令执行官
    ("雷电将军", {"social": 0.1, "goal_oriented": 0.9}, "神樱庭"),  # 将军
]


def banner(t: str) -> None:
    print("\n" + "─" * 72)
    print(t)
    print("─" * 72)


def tiers_str(tiers: dict) -> str:
    return "  ".join(f"{n}={t}" for n, t in tiers.items())


def main() -> int:
    shutil.rmtree(DATA, ignore_errors=True)   # 全新运行, 避免上次记忆污染
    os.makedirs(DATA, exist_ok=True)
    llm = RealLLM()
    emb = make_embedder()

    w = World("稻妻城", LOCATIONS, path=os.path.join(DATA, "world.db"))
    for name, persona, loc in NPCS:
        w.add_npc(name, persona, llm=llm, embedder=emb, data_dir=DATA, location=loc)
    w.add_player("旅行者", "稻妻主城")

    banner("07:00 眼狩令生效 (全图世界事件, 所有 NPC 感知)")
    w.world_event("雷电将军颁布眼狩令: 全城神之眼一律收缴", now=7.0)
    s = w.step(7.0)
    print("档位:", tiers_str(s["tiers"]))

    banner("08:00 旅行者到治疗堂, 帮桃音藏起雷神之眼 (关系事件)")
    w.move("旅行者", "治疗堂", now=8.0)
    w.npc("桃音").observe("旅行者帮 桃音 把雷神之眼藏进了地窖", 8.0, player_id="旅行者")
    s = w.step(8.0)
    print("桃音→旅行者信任:", f"{w.npc('桃音').trust_toward('旅行者'):+.2f}")
    print("档位:", tiers_str(s["tiers"]), "(桃音同区域 full, 将军远离 idle)")

    banner("09:00 旅行者: '藏神之眼真的安全吗?' — speak (非全知对话)")
    print("   桃音:", w.npc("桃音").speak("旅行者", "藏神之眼真的安全吗?", 9.0))

    banner("10:00 旅行者到锻造坊, 与刚郎谈一桩委托 (务实交易)")
    w.move("旅行者", "锻造坊", now=10.0)
    w.npc("刚郎").observe("旅行者 找 刚郎 委托打造武器, 言谈务实, 公平交易", 10.0,
                          player_id="旅行者")
    s = w.step(10.0)
    print("刚郎→旅行者信任:", f"{w.npc('刚郎').trust_toward('旅行者'):+.2f}")

    banner("11:00 旅行者回主城, 小梅打听眼狩令 (好奇)")
    w.move("旅行者", "稻妻主城", now=11.0)
    w.step(11.0)
    print("   小梅:", w.npc("小梅").speak("旅行者", "你怎么看眼狩令?", 11.0))

    banner("12:00 旅行者到眼狩署, 执行官注意到他在帮持眼者 (信任分化)")
    w.move("旅行者", "眼狩署", now=12.0)
    w.npc("执行官").observe("旅行者 被目击帮助 桃音 藏匿神之眼", 12.0, player_id="旅行者")
    s = w.step(12.0)
    print("执行官→旅行者信任:", f"{w.npc('执行官').trust_toward('旅行者'):+.2f}")
    print("档位:", tiers_str(s["tiers"]))

    banner("13:00 世界事件: 执行官搜捕全城神之眼 (眼狩署为中心半径事件)")
    w.world_event("执行官开始搜捕全城的神之眼", now=13.0, at="眼狩署", radius=1.5)
    s = w.step(13.0)
    print("档位:", tiers_str(s["tiers"]))

    banner("14:00 旅行者离开稻妻城 (距离调度: 全员降档)")
    w.move("旅行者", "城外官道", now=14.0)
    s = w.step(14.0)
    print("档位:", tiers_str(s["tiers"]), "(旅行者远离全城 → 全员 idle 省认知)")

    banner("结局: 旅行者对各 NPC 的面 (信任度) — 千人千面")
    for name, _, _ in NPCS:
        print(f"   {name}: {w.npc(name).trust_toward('旅行者'):+.2f}")
    print("\n桃音(受助)信任高 / 刚郎(务实交易)信任中 / 执行官(藏匿神之眼)警惕 / "
          "小梅(好奇)中性偏正 / 雷电将军疏离 (旅行者从未接近, 始终 idle, 从未感知到旅行者)")
    w.close()
    print(f"\n世界状态已存: {os.path.abspath(DATA)}/world.db  (每 NPC 独立 <name>.db)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
