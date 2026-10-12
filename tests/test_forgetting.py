"""遗忘/衰减测试 (无网络, stub LLM): 保护、衰减、近期留存、自动清扫。"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from persona_agent import NPC, MemoryRecord
from persona_agent.memory import FORGET_FLOOR
from tests.test_persistence import _StubLLM, TRAITS


def _make(tmp_path) -> NPC:
    return NPC.create("Fade", dict(TRAITS), llm=_StubLLM(), data_dir=str(tmp_path))


def test_uncited_old_observation_forgotten(tmp_path):
    """未被反思引用的旧观察, 远期会被遗忘。"""
    npc = _make(tmp_path)
    old = npc.observe("Fade 扫地", 0.0)                 # 世界观察, 无引用
    npc.observe("Aria 帮 Fade 修了咖啡机", 0.0, player_id="Aria")
    npc.forget(now=720.0)                                # 30 天后
    ids = {m.id for m in npc.store.all_valid(types=["observation"])}
    assert old not in ids, "未引用的旧观察应被遗忘"


def test_cited_observation_protected(tmp_path):
    """被有效反思引用为证据的观察受保护, 不遗忘。"""
    npc = _make(tmp_path)
    cited = npc.observe("Aria 帮 Fade 修了咖啡机", 0.0, player_id="Aria")
    npc.store.add(MemoryRecord(content="Aria 是值得信赖的伙伴",
                               timestamp=1.0, type="reflection",
                               player_id="Aria", evidence=[cited],
                               confidence=0.8))
    npc.forget(now=720.0)
    ids = {m.id for m in npc.store.all_valid(types=["observation"])}
    assert cited in ids, "被反思引用的观察应受保护"


def test_recent_memory_survives(tmp_path):
    """近期记忆不在遗忘之列。"""
    npc = _make(tmp_path)
    fresh = npc.observe("Aria 今天送了一杯新豆子", 700.0, player_id="Aria")
    npc.forget(now=720.0)                                # 仅 20h 前
    ids = {m.id for m in npc.store.all_valid(types=["observation"])}
    assert fresh in ids


def test_old_reflection_fades(tmp_path):
    """低置信度的旧反思, 远期衰减到阈值以下被遗忘。"""
    npc = _make(tmp_path)
    ref_id = npc.store.add(MemoryRecord(content="Aria 似乎喜欢咖啡",
                                        timestamp=0.0, type="reflection",
                                        player_id="Aria", evidence=[],
                                        confidence=FORGET_FLOOR + 0.05))
    npc.forget(now=1000.0)                               # ~41 天
    ids = {m.id for m in npc.store.all_valid(types=["reflection"])}
    assert ref_id not in ids


def test_auto_sweep_on_time_advance(tmp_path):
    """游戏时钟跨 SWEEP_INTERVAL 时, observe 自动触发遗忘清扫。"""
    from persona_agent.npc import SWEEP_INTERVAL
    npc = _make(tmp_path)
    old = npc.observe("Fade 擦桌子", 0.0)                # _last_sweep 设为 0
    # 第二次 observe 把时钟推到 200h 后: 跨越清扫间隔 → 自动清扫;
    # 旧观察 age=200h, 强度 0.5*0.5^(200/48)≈0.03 < 阈值 → 被遗忘
    npc.observe("Aria 来了", SWEEP_INTERVAL + 194.0, player_id="Aria")
    ids = {m.id for m in npc.store.all_valid(types=["observation"])}
    assert old not in ids
