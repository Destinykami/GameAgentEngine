"""源码重排后，旧导入必须委托到同一模块，不能生成两套类或补丁状态。"""

from importlib import import_module
from pathlib import Path
import os
import subprocess
import sys

import pytest


LEGACY_MODULES = {
    "npc": "cognition.npc", "reflection": "cognition.reflection",
    "planning": "cognition.planning", "reacting": "cognition.reacting",
    "dialogue": "cognition.dialogue", "autonomous": "cognition.autonomous",
    "memory": "memory.store", "memory_model": "memory.models",
    "memory_ranking": "memory.ranking", "memory_policy": "memory.policies",
    "memory_repository": "memory.repository", "world": "world.runtime",
    "world_model": "world.entities", "actions": "world.actions",
    "perception": "world.perception", "events": "world.events",
    "world_extensions": "world.extensions", "world_store": "world.persistence",
    "social": "world.social", "social_contracts": "world.social_contracts",
    "llm": "models.llm", "llm_real": "models.llm_http",
    "embeddings": "models.embeddings", "embeddings_real": "models.embeddings_http",
    "probes": "evaluation.probes",
}


def test_legacy_submodules_are_the_same_canonical_modules():
    for legacy, canonical in LEGACY_MODULES.items():
        assert import_module(f"persona_agent.{legacy}") is import_module(
            f"game_agent.{canonical}"), legacy


def test_legacy_public_exports_keep_identity():
    import game_agent
    import persona_agent

    assert persona_agent.__all__ == game_agent.__all__
    assert persona_agent.__version__ == game_agent.__version__
    for name in game_agent.__all__:
        assert getattr(persona_agent, name) is getattr(game_agent, name), name


def test_monkeypatch_through_legacy_path_affects_canonical_module(monkeypatch):
    legacy = import_module("persona_agent.llm_real")
    canonical = import_module("game_agent.models.llm_http")
    monkeypatch.setattr(legacy, "DEFAULT_MODEL", "test-layout-model")
    assert canonical.DEFAULT_MODEL == "test-layout-model"


@pytest.mark.parametrize("legacy", ["world_model", "memory_model", "events"])
def test_legacy_foundation_import_stays_lightweight(legacy):
    result = subprocess.run([sys.executable, "-c", f'''
import importlib
import sys
importlib.import_module("persona_agent.{legacy}")
for name in ("game_agent.world.runtime", "game_agent.cognition.npc",
             "game_agent.memory.store", "game_agent.models.llm_http", "sqlite3"):
    assert name not in sys.modules, name
'''], env=dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1] / "src")),
        capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
