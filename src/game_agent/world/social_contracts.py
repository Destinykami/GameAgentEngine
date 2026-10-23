"""社交层与 NPC 认知之间的数据和窄接口。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class Hearsay:
    content: str
    player_id: str | None
    hop: int


class SocialCognition(Protocol):
    name: str

    def perceive_action(self, player_name: str, action: str, now: float) -> int: ...

    def observe(self, content: str, now: float, player_id: str | None = None,
                hearsay: bool = False, hop: int = 0) -> int: ...

    def maybe_reflect_relationship(self, player_id: str, now: float) -> list[int]: ...

    def rumor_to_share(self, query: str, now: float) -> Hearsay | None: ...
