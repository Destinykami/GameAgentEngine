"""单 NPC 运行状态；不创建模型、记忆库或认知组件。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field, replace

REFLECTION_THRESHOLD = 150.0
SWEEP_INTERVAL = 6.0


@dataclass
class RuntimeState:
    reflection_threshold: float = REFLECTION_THRESHOLD
    importance_accum: float = 0.0
    tier: str = "full"
    reflected_obs: dict[str, int] = field(default_factory=dict)
    shared_conflict_sig: tuple | None = None
    data_path: str | None = None
    game_time: float = 0.0
    last_sweep: float | None = None

    def advance(self, now: float, forget: Callable[[float], list[int]]) -> None:
        if now > self.game_time:
            self.game_time = now
        if self.last_sweep is None:
            self.last_sweep = now
        elif now - self.last_sweep >= SWEEP_INTERVAL:
            forget(now)
            self.last_sweep = now

    def record_observation(self, importance: float, player_id: str | None) -> None:
        if self.tier != "idle" and player_id is None:
            self.importance_accum += importance

    def set_tier(self, tier: str) -> None:
        assert tier in ("full", "compressed", "idle")
        self.tier = tier

    def snapshot(self) -> RuntimeState:
        """诊断副本；关系反思水位不与实际运行共享可变对象。"""
        return replace(self, reflected_obs=dict(self.reflected_obs))
