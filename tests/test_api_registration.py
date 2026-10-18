"""add_npc 自治注册 / register_agent / load 恢复回归 (F5-1)。"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from persona_agent import HashEmbedder, Location, World
from tests.test_persistence import _StubLLM, TRAITS


def _world(tmp_path) -> World:
    return World("w", [Location("L", 0, 0)], path=str(tmp_path / "world.db"))


def test_add_npc_default_is_cognition_only(tmp_path):
    w = _world(tmp_path)
    w.add_npc("A", dict(TRAITS), llm=_StubLLM(),
              data_dir=str(tmp_path / "A"), location="L")
    decisions = w.decide_agent(w.get("A"))
    assert decisions["reason"] == "无 LLM", "缺省不注册自治 agent, 保持旧行为"
    w.close()


def test_add_npc_autonomous_registers(tmp_path):
    w = _world(tmp_path)
    w.add_npc("A", dict(TRAITS), llm=_StubLLM(),
              data_dir=str(tmp_path / "A"), location="L", autonomous=True)
    assert "A" in w._agent_llms and "A" in w._agent_personas
    decisions = w.decide_agent(w.get("A"))
    assert decisions["reason"] != "无 LLM", "自治 NPC 应可被决策"
    w.close()


def test_register_agent_public_api(tmp_path):
    w = _world(tmp_path)
    w.add_npc("A", dict(TRAITS), llm=_StubLLM(),
              data_dir=str(tmp_path / "A"), location="L")
    w.register_agent("A", _StubLLM(), dict(TRAITS))
    assert w.decide_agent(w.get("A"))["reason"] != "无 LLM"
    w.close()


def test_load_restores_autonomous_registration(tmp_path):
    w = _world(tmp_path)
    w.add_npc("A", dict(TRAITS), llm=_StubLLM(),
              data_dir=str(tmp_path / "A"), location="L", autonomous=True)
    w.save()
    w.close()

    w2 = _world(tmp_path)
    w2.load(llm=_StubLLM(), embedder=HashEmbedder())
    assert "A" in w2._agent_llms
    assert w2.decide_agent(w2.get("A"))["reason"] != "无 LLM"
    w2.close()
