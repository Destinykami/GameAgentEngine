"""脚本周剧情的终端认知快照与汇总。"""

from __future__ import annotations

from typing import TYPE_CHECKING
from .definition import SCRIPTED_NPCS as NPCS

if TYPE_CHECKING:
    from ...world.runtime import World


def banner(t: str) -> None:
    print("\n" + "═" * 78)
    print(t)
    print("═" * 78)


def sub(t: str) -> None:
    print("\n" + "─" * 78)
    print(t)
    print("─" * 78)


def tiers_str(tiers: dict) -> str:
    return "  ".join(f"{n}={t}" for n, t in tiers.items())


def say(npc_name: str, traveler_says: str, npc_replies: str) -> None:
    """打印一段对话: 旅行者说 (脚本驱动, 是喂给 speak 的输入) + NPC 回
    (NPC 自己用 LLM 非全知生成, 只用它自己的记忆流)。

    npc_name 是对话对象 (回复由谁生成、第二句标谁), 不是第一句的说话人。
    """
    print(f"   旅行者: {traveler_says}")
    print(f"   {npc_name}: {npc_replies}")


def snapshot(w: World, day_label: str) -> None:
    sub(f"{day_label} — 每个 NPC 的认知表现")
    for name, _, _, role in NPCS:
        npc = w.npc(name)
        loc = w.entities[name].location.name
        trust = npc.trust_toward("旅行者")
        n_obs = len(npc.store.all_valid(types=["observation"]))
        refl = npc.store.all_valid(types=["reflection"])
        self_refl = [r.content for r in refl if r.player_id is None]
        rel_refl = [r.content for r in refl if r.player_id == "旅行者"]
        last_self = self_refl[-1] if self_refl else "· (尚未累积到自我反思阈值)"
        last_rel = rel_refl[-1] if rel_refl else "· (尚未建立对旅行者的关系认知)"
        print(f"\n[{loc}] {name} ({role})")
        print(f"   档位={npc.tier:<11} 信任→旅行者={trust:+.2f}   "
              f"记忆: 观察{n_obs} / 反思{len(refl)}")
        print(f"   自我反思: {last_self}")
        print(f"   对旅行者的关系反思: {last_rel}")


def trust_row(w: World) -> dict:
    return {name: round(w.npc(name).trust_toward("旅行者"), 2)
            for name, _, _, _ in NPCS}
