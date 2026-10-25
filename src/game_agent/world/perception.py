"""空间可见性、认知档位和在场变化；不依赖世界运行或具体 NPC。"""

from __future__ import annotations

from collections.abc import Callable, Collection, Iterable
from typing import Protocol

from .entities import Entity, distance


def visible_entities(observer: Entity, entities: Iterable[Entity],
                     radius: float) -> list[Entity]:
    return [other for other in entities
            if other is not observer and not other.dead
            and distance(observer, other) <= radius]


def cognitive_tier(observer: Entity, entities: Iterable[Entity],
                   full_radius: float, perception_radius: float) -> str:
    if observer.dead:
        return "idle"
    nearest = min((distance(observer, other) for other in entities
                   if other.kind == "player" and not other.dead), default=None)
    if nearest is None:
        return "idle"
    if nearest <= full_radius:
        return "full"
    if nearest <= perception_radius:
        return "compressed"
    return "idle"


class ObservationSink(Protocol):
    name: str

    @property
    def tier(self) -> str: ...

    def observe(self, content: str, now: float,
                player_id: str | None = None) -> int: ...


class PresenceTracker:
    """每个世界独立的在场水位，观察写入通过窄接口交给认知层。"""

    def __init__(self) -> None:
        self._player_seen: dict[str, dict[str, tuple[str, str]]] = {}
        self._social_seen: dict[str, set[str]] = {}

    def checkpoint_state(self) -> dict:
        return {"players": {name: {other: list(key) for other, key in seen.items()}
                            for name, seen in self._player_seen.items()},
                "social": {name: sorted(seen) for name, seen in self._social_seen.items()}}

    def restore_checkpoint(self, state: dict) -> None:
        self._player_seen = {name: {other: tuple(key) for other, key in seen.items()}
                             for name, seen in state["players"].items()}
        self._social_seen = {name: set(seen) for name, seen in state["social"].items()}

    def perceive(self, me: Entity, npc: ObservationSink,
                 entities: Collection[Entity], now: float, radius: float, *,
                 social_perception: bool, player_transition: bool,
                 on_social: Callable[[str], None]) -> list[int]:
        if npc.tier == "idle":
            return []
        if me.dead:
            return []   # 死去的 NPC 不再感知 (同 world_event/step 的死亡检查)
        ids: list[int] = []
        transition = player_transition
        seen = self._player_seen.setdefault(npc.name, {}) if transition else None
        current: set[str] = set()
        for ent in entities:
            if ent.kind != "player" or ent.dead or distance(me, ent) > radius:
                continue   # 非玩家 / 死者 / 视距外
            if transition:
                current.add(ent.name)
                key = (ent.location.name, npc.tier)
                if seen.get(ent.name) == key:
                    continue   # F6-11: 过渡驱动, 同一在场状态不重复 observe
                seen[ent.name] = key
            if npc.tier == "full":
                content = f"{ent.name} 出现在 {me.location.name}, 靠近 {npc.name}"
            else:   # compressed
                content = f"{ent.name} 在 {me.location.name}"
            ids.append(npc.observe(content, now, player_id=ent.name))
        if transition:
            for pname in [n for n in seen if n not in current]:
                seen.pop(pname, None)   # 离开视距 → 重进时重新观察
        # S2 社交在场感知 (缺省关): NPC 感知视距内其他 NPC 的**出现**。
        # 过渡驱动而非逐步重放: 只对新进入视距的 NPC 产生观察 (重复在场不重复
        # 入库, 0.92 去重仍是兜底); 离开视距即移出 seen, 重现会再触发。
        # 档位同玩家感知: full=富细节, compressed=仅在场, idle 经入口早退无感知。
        # 新观察通过 on_social 通知运行器；关系反思的时机与队列由运行器管理。
        if social_perception:
            seen = self._social_seen.setdefault(npc.name, set())
            current: set[str] = set()
            for ent in entities:
                if (ent.kind != "npc" or ent is me or ent.dead
                        or distance(me, ent) > radius):
                    continue
                current.add(ent.name)
            for other in sorted(current - seen):
                if npc.tier == "full":
                    content = f"{other} 出现在 {me.location.name}, 靠近 {npc.name}"
                else:   # compressed
                    content = f"{other} 在 {me.location.name}"
                ids.append(npc.observe(content, now, player_id=other))
                on_social(other)
            # 就地更新 seen 为当前在场集合 (不能 seen &= current: 首步 seen 为空,
            # 交集恒空, 出现集合记不住, 每步都当"新出现")。离开者自然移出, 重现再触发。
            seen.clear()
            seen.update(current)
        return ids
