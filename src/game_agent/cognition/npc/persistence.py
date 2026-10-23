"""NPC 元数据与恢复规则；数据库连接和 NPC 创建由编排工厂负责。"""

from __future__ import annotations

import os
from typing import Any

from ..planning.state import PlanState
from .contracts import MetadataMemory
from .state import REFLECTION_THRESHOLD, RuntimeState


def prepare_path(name: str, data_dir: str) -> tuple[str, bool]:
    os.makedirs(data_dir, exist_ok=True)
    path = os.path.join(data_dir, f"{name}.db")
    return path, os.path.exists(path)


def load_configuration(store: MetadataMemory, path: str,
                        reflection_threshold: float | None) -> tuple[dict[str, Any], float]:
    meta = store.get_meta("npc")
    if not meta:
        raise ValueError(f"{path} 中没有 NPC 元数据 (不是 NPC 库)")
    threshold = (reflection_threshold
                 if reflection_threshold is not None
                 else meta.get("reflection_threshold", REFLECTION_THRESHOLD))
    return meta, threshold


def restore_runtime(store: MetadataMemory, state: RuntimeState) -> PlanState:
    state.game_time = float(store.get_meta("game_time", 0.0))
    reflected = store.get_meta("reflected_obs", {}) or {}
    state.reflected_obs = {str(k): int(v) for k, v in reflected.items()}
    plan_state = PlanState.from_saved(store.get_meta("plan_blocks", []))
    state.last_sweep = state.game_time
    return plan_state


def save_checkpoint(store: MetadataMemory, name: str, persona_traits: dict[str, float],
                     state: RuntimeState, plan_state: PlanState) -> None:
    if not store.is_persistent():
        raise RuntimeError("该 NPC 使用 :memory: 库, 无法持久化 "
                           "(请用 NPC.create / NPC.load 创建)")
    # 保留逐键提交顺序，不在结构拆分中新增事务或持久化字段。
    store.set_meta("npc", {"name": name, "persona_traits": persona_traits,
                           "reflection_threshold": state.reflection_threshold})
    store.set_meta("game_time", state.game_time)
    store.set_meta("reflected_obs", dict(state.reflected_obs))
    store.set_meta("plan_blocks", plan_state.saved_blocks())
    if state.data_path is None:
        state.data_path = store.db_path()
