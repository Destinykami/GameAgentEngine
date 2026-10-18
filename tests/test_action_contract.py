"""动作空间契约回归 (F3-3 / F3-4)。

- 目标不在视距内/不存在 → 交互中止, 不扣血、不写历史、不对话。
- help/hide 的认知事件失败 → 不动最终状态 (原子性)。
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from persona_agent import Location, World
from tests.test_persistence import _StubLLM, TRAITS


def _world(tmp_path) -> World:
    w = World("w", [Location("近", 0, 0), Location("远", 100, 100)])
    w.add_npc("A", dict(TRAITS), llm=_StubLLM(),
              data_dir=str(tmp_path / "A"), location="近")
    w.add_npc("B", dict(TRAITS), llm=_StubLLM(),
              data_dir=str(tmp_path / "B"), location="远")
    return w


def test_interaction_out_of_range_is_rejected(tmp_path):
    w = _world(tmp_path)
    before_health = w.get("B").health
    for act in ({"action": "attack", "target": "B"},
                {"action": "talk", "target": "B", "utterance": "你好"},
                {"action": "help", "target": "B"}):
        out = w.execute_action(w.get("A"), act)
        assert "不在可交互范围" in out
        ve = w.visual_events[-1]
        assert ve.success is False
    assert w.get("B").health == before_health, "隔空攻击不得扣血"
    assert w.get("B").history == [], "隔空动作不得写目标历史"
    assert w.get("A").history == [], "隔空动作不得写行动者历史"
    w.close()


def test_interaction_in_range_succeeds(tmp_path):
    w = _world(tmp_path)
    w.move("B", "近", now=1.0)
    out = w.execute_action(w.get("A"), {"action": "help", "target": "B"})
    assert "帮助" in out
    assert w.visual_events[-1].success is True
    assert w.get("B").history, "成功帮助应写目标历史"
    w.close()


class _BoomPerceive(_StubLLM):
    def perceive_action(self, npc_name, player_name, action, context=""):
        raise RuntimeError("perceive failed")


def test_help_cognitive_failure_is_atomic(tmp_path):
    w = World("w", [Location("L", 0, 0)])
    w.add_npc("A", dict(TRAITS), llm=_StubLLM(),
              data_dir=str(tmp_path / "A"), location="L")
    w.add_npc("B", dict(TRAITS), llm=_BoomPerceive(),
              data_dir=str(tmp_path / "B"), location="L")
    out = w.execute_action(w.get("A"), {"action": "help", "target": "B"})
    assert "认知事件生成失败" in out
    assert w.visual_events[-1].success is False
    assert w.get("A").history == [], "认知失败不得提交行动者历史"
    assert w.get("B").history == [], "认知失败不得提交目标历史"
    w.close()
