"""自治运行的终端摘要与时间线实体快照。"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..world.runtime import World


def banner(text: str) -> None:
    print(f"\n{'═' * 70}\n{text}\n{'═' * 70}")


def status_line(w: World) -> str:
    """每个存活 agent 的血/位置; 旅行者额外显示已收集证据数/攻 (涌现, 无门槛)。"""
    parts = []
    for name, e in w.entities.items():
        if e.is_alive():
            base = f"{name}血{e.health}@{e.location.name}"
            if e.kind == "player":
                base += f"(证据{len(e.reasons)}条,攻{e.attack})"
            parts.append(base)
        else:
            parts.append(f"{name}✝")
    return " | ".join(parts)


def snapshot(w: World) -> dict:
    """抓一个世界状态快照 (供回放): 每个 agent 的血/位置/理由/攻/角色/存活。"""
    return {
        name: {"health": e.health, "loc": e.location.name, "dead": e.dead,
               "reasons": list(e.reasons), "attack": e.attack, "role": e.role,
               "kind": e.kind}
        for name, e in w.entities.items()
    }



def timeline_metadata(world_name: str) -> dict:
    return {"schema_version": 1,
            "world": {"name": world_name, "coordinate_system": "location-name",
                      "render_map": "inazuma-v1"},
            "reason_needed": None, "attack_needed": None, "persuade_n": None}
