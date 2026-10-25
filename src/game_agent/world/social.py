"""社交观察队列和传闻路由；记忆选择与反思门控归认知端口。"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import TypeVar

from .social_contracts import SocialCognition
from .entities import Entity, location_distance

_Cognition = TypeVar("_Cognition", bound=SocialCognition)


class SocialRuntime:
    def __init__(self) -> None:
        self.pending: list[tuple[SocialCognition, str]] = []

    def checkpoint_state(self) -> list[list[str]]:
        return [[npc.name, actor] for npc, actor in self.pending]

    def restore_checkpoint(self, rows: list, cognitions: Mapping[str, SocialCognition]) -> None:
        self.pending = [(cognitions[name], actor) for name, actor in rows]

    def enqueue(self, cognition: SocialCognition, actor_id: str) -> None:
        self.pending.append((cognition, actor_id))

    def observe_action(self, cognition: _Cognition | None, actor_id: str,
                       description: str, now: float) -> _Cognition | None:
        if cognition is None:
            return None
        cognition.perceive_action(actor_id, description, now)
        self.enqueue(cognition, actor_id)
        return cognition

    def flush(self, now: float, is_alive: Callable[[str], bool]) -> None:
        try:
            for cognition, actor_id in self.pending:
                try:
                    if is_alive(cognition.name):
                        cognition.maybe_reflect_relationship(actor_id, now)
                except Exception:
                    continue
        finally:
            self.pending.clear()

    def spread_rumor(self, speaker: Entity, listener: Entity, line: str, *,
                     now: float, radius: float, entities: Mapping[str, Entity],
                     cognitions: Mapping[str, SocialCognition]) -> None:
        for name, cognition in cognitions.items():
            ent = entities.get(name)
            if ent is None or ent.dead or ent is speaker or ent is listener:
                continue
            if location_distance(speaker.location, ent) > radius:
                continue
            cognition.observe(f"{speaker.name} 说: {line}", now,
                              player_id=speaker.name, hearsay=True, hop=1)
            self.enqueue(cognition, speaker.name)
        speaker_npc = cognitions.get(speaker.name)
        listener_npc = cognitions.get(listener.name)
        if speaker_npc is None or listener_npc is None:
            return
        rumor = speaker_npc.rumor_to_share(line, now)
        if rumor is None or rumor.player_id == listener.name:
            return
        if rumor.content.startswith(f"{listener.name} 告诉我:"):
            return
        listener_npc.observe(f"{speaker.name} 告诉我: {rumor.content}", now,
                             player_id=rumor.player_id, hearsay=True,
                             hop=rumor.hop + 1)
        self.enqueue(listener_npc, rumor.player_id or speaker.name)
