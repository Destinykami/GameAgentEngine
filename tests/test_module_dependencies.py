"""在新进程检查独立模块的运行时依赖边界与兼容导出。"""

from pathlib import Path
import subprocess
import sys

import pytest


@pytest.mark.parametrize("module", [
    "world_model", "events", "perception", "autonomous", "world_extensions",
    "social", "actions", "memory_model", "memory_policy", "memory_ranking",
])
def test_foundation_import_does_not_load_runtime_or_model_adapters(module):
    code = f'''
import importlib
import sys
importlib.import_module("persona_agent.{module}")
for name in ("persona_agent.world", "persona_agent.npc", "persona_agent.memory",
             "persona_agent.llm_real", "persona_agent.embeddings_real", "sqlite3"):
    assert name not in sys.modules, name
'''
    result = subprocess.run([sys.executable, "-c", code],
                            cwd=Path(__file__).resolve().parents[1],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_lazy_public_exports_preserve_legacy_identity_and_discovery():
    import persona_agent
    from persona_agent import memory, memory_model, world, world_model

    scope = {}
    exec("from persona_agent import *", scope)
    assert set(persona_agent.__all__) <= scope.keys()
    assert set(persona_agent.__all__) <= set(dir(persona_agent))
    assert scope["World"] is world.World
    assert scope["MemoryRecord"] is memory.MemoryRecord is memory_model.MemoryRecord
    for name in ("Location", "Entity", "Player", "distance", "location_distance"):
        assert scope[name] is getattr(world, name) is getattr(world_model, name)
    with pytest.raises(AttributeError):
        getattr(persona_agent, "missing_public_api")


def test_public_memory_record_does_not_load_sqlite():
    result = subprocess.run([sys.executable, "-c", '''
import sys
from persona_agent import MemoryRecord
assert MemoryRecord("记忆", 0.0).content == "记忆"
assert "sqlite3" not in sys.modules
assert "persona_agent.memory" not in sys.modules
'''], cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
