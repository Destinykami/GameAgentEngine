"""遗忘测试 (无网络, stub LLM): 部分衰减降权, 不删除。

遗忘现在是"降权"不是"抹除": 久未访问的记忆 importance 渐近降到
MIN_IMPORTANCE, 但 valid 恒为 1 (不失效)。被反思引用的观察受保护不降权,
被回忆过 (last_accessed) 的记忆衰减更慢。
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from persona_agent import NPC, MemoryRecord
from persona_agent.memory import MIN_IMPORTANCE
from tests.test_persistence import _StubLLM, TRAITS


def _make(tmp_path) -> NPC:
    return NPC.create("Fade", dict(TRAITS), llm=_StubLLM(), data_dir=str(tmp_path))


def _by_id(npc, mem_type):
    return {m.id: m for m in npc.store.all_valid(types=[mem_type])}


def test_uncited_old_observation_downweighted_not_deleted(tmp_path):
    """未被反思引用的旧观察: 降权到 MIN_IMPORTANCE, 但保留 (不删除)。"""
    npc = _make(tmp_path)
    old = npc.observe("Fade 扫地", 0.0)                 # 世界观察, 无引用, importance 5.0
    npc.forget(now=720.0)                                # 30 天后
    obs = _by_id(npc, "observation")
    assert old in obs, "旧观察应保留 (降权不删除)"
    assert obs[old].importance == pytest.approx(MIN_IMPORTANCE), \
        "未引用的旧观察 importance 应降到下限"


def test_cited_observation_protected(tmp_path):
    """被有效反思引用为证据的观察受保护: importance 不降权, 保留。"""
    npc = _make(tmp_path)
    cited = npc.observe("Aria 帮 Fade 修了咖啡机", 0.0, player_id="Aria")
    npc.store.add(MemoryRecord(content="Aria 是值得信赖的伙伴",
                               timestamp=1.0, type="reflection",
                               player_id="Aria", evidence=[cited],
                               confidence=0.8))
    npc.forget(now=720.0)
    obs = _by_id(npc, "observation")
    assert cited in obs, "被反思引用的观察应保留"
    assert obs[cited].importance == pytest.approx(5.0), \
        "被引用的观察受保护, importance 不应降权"


def test_recent_memory_retains_importance(tmp_path):
    """近期记忆: 降权但远高于下限, 保留。"""
    npc = _make(tmp_path)
    fresh = npc.observe("Aria 今天送了一杯新豆子", 700.0, player_id="Aria")
    npc.forget(now=720.0)                                # 仅 20h 前
    obs = _by_id(npc, "observation")
    assert fresh in obs
    assert obs[fresh].importance > MIN_IMPORTANCE, "近期记忆不应被降到下限"
    assert obs[fresh].importance < 5.0, "近期记忆仍会被轻微降权"


def test_old_reflection_downweighted_not_deleted(tmp_path):
    """旧反思: 降权到 MIN_IMPORTANCE, 但保留 (不删除)。"""
    npc = _make(tmp_path)
    ref_id = npc.store.add(MemoryRecord(content="Aria 似乎喜欢咖啡",
                                        timestamp=0.0, type="reflection",
                                        player_id="Aria", evidence=[],
                                        confidence=0.5))
    npc.forget(now=1000.0)                               # ~41 天
    refs = _by_id(npc, "reflection")
    assert ref_id in refs, "旧反思应保留 (降权不删除)"
    assert refs[ref_id].importance == pytest.approx(MIN_IMPORTANCE)


def test_recalled_memory_decays_slower(tmp_path):
    """被回忆过 (last_accessed 刷新) 的记忆衰减更慢: 同一时刻, 被回忆的仍高于
    下限, 从未被回忆的已触底。"""
    npc = _make(tmp_path)
    recalled = npc.observe("Aria 帮 Fade 修了咖啡机", 0.0, player_id="Aria")
    never = npc.observe("Fade 擦桌子", 0.0)                # 对照: 从不被回忆
    npc.store.merge_observation(recalled, now=240.0, extra_importance=1.0)
    # merge 刷新 last_accessed=240, importance 5.0→6.0
    npc.forget(now=300.0)
    obs = _by_id(npc, "observation")
    # 被回忆: age=60h, factor=0.5^1.25≈0.42, 6.0*0.42≈2.52 → 高于下限
    # 未回忆: age=300h, factor≈0.013, 5.0*0.013≈0.06 → 触底 1.5
    assert obs[recalled].importance > MIN_IMPORTANCE, "被回忆记忆衰减更慢, 仍高于下限"
    assert obs[never].importance == pytest.approx(MIN_IMPORTANCE), "未回忆记忆触底"


def test_auto_sweep_on_time_advance(tmp_path):
    """游戏时钟跨 SWEEP_INTERVAL 时, observe 自动触发遗忘清扫 (降权)。"""
    from persona_agent.npc import SWEEP_INTERVAL
    npc = _make(tmp_path)
    old = npc.observe("Fade 擦桌子", 0.0)                # _last_sweep 设为 0
    # 第二次 observe 把时钟推到 200h 后: 跨越清扫间隔 → 自动清扫;
    # 旧观察 age=200h, factor=0.5^(200/48)≈0.035, 5.0*0.035≈0.18 → 降到下限
    npc.observe("Aria 来了", SWEEP_INTERVAL + 194.0, player_id="Aria")
    obs = _by_id(npc, "observation")
    assert old in obs, "自动清扫应降权而非删除"
    assert obs[old].importance == pytest.approx(MIN_IMPORTANCE)
