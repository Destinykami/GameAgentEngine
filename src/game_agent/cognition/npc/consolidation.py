"""按关系流固化观察；时钟推进与共享冲突触发由 NPC 编排。"""

from __future__ import annotations

from ...memory.models import MemoryRecord
from .contracts import ConsolidationMemory, ConsolidationModel


def consolidate_observations(store: ConsolidationMemory, model: ConsolidationModel,
                              now: float) -> list[int]:
    day_start = now - 24.0
    new_ids: list[int] = []
    # 流分组 (确定性顺序): 共享流先, 各玩家面按名字排序。
    # E2 陷阱: all_valid(player_id=None) 是"不过滤"不是共享流 —— 共享流必须
    # shared=True, 否则共享流的循环会把全部观察 (含玩家面) 一次全吃掉。
    player_ids = sorted({m.player_id for m in
                         store.all_valid(types=["observation"])
                         if m.player_id is not None})
    for shared, pid in [(True, None)] + [(False, p) for p in player_ids]:
        obs = [m for m in store.all_valid(shared=shared, player_id=pid,
                                         types=["observation"],
                                         consolidated=False)
               if m.timestamp >= day_start]
        if len(obs) < 2:   # 单条观察本身已是摘要, 无需压缩
            continue
        summary = model.consolidate_observations(
            [m.content for m in obs], pid)
        if not summary or not summary.strip():
            continue
        # F4-2: episode 继承来源。任一条原料是传闻则标 hearsay; hop 取
        # 最远来源 (保守: 摘要的可信度不高于其最弱原料)。
        ep = MemoryRecord(content=summary.strip(), timestamp=now,
                          type="episode", player_id=pid,
                          evidence=[m.id for m in obs if m.id is not None],
                          confidence=min(m.confidence for m in obs),
                          base_confidence=min(m.confidence for m in obs),
                          importance=max(m.importance for m in obs),
                          hearsay=any(m.hearsay for m in obs),
                          hop=max((m.hop for m in obs if m.hearsay),
                                  default=0))
        ep_id = store.add(ep)
        store.mark_consolidated([m.id for m in obs])
        new_ids.append(ep_id)
    return new_ids
