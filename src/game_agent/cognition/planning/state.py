"""当前计划状态及既有计划块快照，不访问模型或记忆。"""

from __future__ import annotations

from dataclasses import dataclass, field

from .rules import PlanBlock


@dataclass
class PlanState:
    blocks: list[PlanBlock] = field(default_factory=list)
    interruption: str = ""

    def replace(self, blocks: list[PlanBlock], interruption: str = "") -> None:
        self.blocks = blocks
        self.interruption = interruption

    def current_activity(self, now: float) -> str:
        hour = now % 24
        for start, end, activity in self.blocks:
            if start <= hour < end:
                return activity
        return ""

    def context(self, now: float, explicit: str | None = None) -> str:
        if explicit is not None:
            return explicit
        return self.current_activity(now) or self.interruption

    def saved_blocks(self) -> list[list]:
        return [list(block) for block in self.blocks]

    @classmethod
    def from_saved(cls, blocks) -> PlanState:
        restored: list[PlanBlock] = []
        for block in blocks or []:
            if (isinstance(block, (list, tuple)) and len(block) == 3
                    and isinstance(block[0], (int, float))
                    and isinstance(block[1], (int, float))):
                restored.append((int(block[0]), int(block[1]), str(block[2])))
        return cls(blocks=restored)
