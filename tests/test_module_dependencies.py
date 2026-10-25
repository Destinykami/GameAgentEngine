"""在新进程检查独立模块的运行时依赖边界与兼容导出。"""

from pathlib import Path
import os
import subprocess
import sys

import pytest


@pytest.mark.parametrize("module", [
    "world.checkpoints", "world.errors", "world.entities", "world.events", "world.perception", "cognition.autonomous",
    "world.extensions", "world.social", "world.actions", "memory.models",
    "memory.policies", "memory.ranking", "memory.events", "world", "memory", "models",
    "cognition", "cognition.game", "evaluation", "integration", "integration.contracts", "integration.state",
    "adapters", "adapters.spatial", "scenarios.werewolf", "scenarios.werewolf.world",
    "cognition.reflection", "cognition.reflection.engine",
    "cognition.reflection.contracts", "cognition.reflection.policies",
    "cognition.reflection.writing", "cognition.reflection.conflicts",
    "cognition.planning", "cognition.planning.engine",
    "cognition.planning.contracts", "cognition.planning.rules",
    "cognition.planning.memory", "cognition.planning.state",
    "cognition.dialogue", "cognition.dialogue.engine",
    "cognition.dialogue.context", "cognition.dialogue.contracts",
    "cognition.dialogue.exchange",
    "cognition.reacting", "cognition.reacting.engine",
    "cognition.reacting.trust", "cognition.reacting.scoring",
    "cognition.reacting.policy", "cognition.reacting.contracts",
    "cognition.npc", "cognition.npc.state", "cognition.npc.contracts",
    "cognition.npc.observation", "cognition.npc.consolidation",
    "cognition.npc.context", "cognition.npc.reactions", "cognition.npc.persistence",
    "models.config", "models.llm_http", "models.llm_http.parsing",
    "models.llm_http.usage", "models.llm_http.dialogue", "models.llm_http.memory",
    "models.llm_http.planning", "models.llm_http.actions", "models.llm_http.game",
    "scenarios", "scenarios.inazuma", "scenarios.inazuma.definition",
    "scenarios.inazuma.effects", "scenarios.inazuma.judgment", "scenarios.inazuma.outcome",
    "scenarios.inazuma.setup", "scenarios.inazuma.scripted", "scenarios.inazuma.reporting",
    "runners", "runners.artifacts", "runners.presentation",
    "evaluation.metrics", "evaluation.artifacts",
    "runners.replay", "runners.replay.cli", "runners.replay.terminal", "runners.replay.html",
])
def test_foundation_import_does_not_load_runtime_or_model_adapters(module):
    code = f'''
import importlib
import sys
importlib.import_module("game_agent.{module}")
for name in ("game_agent.world.runtime", "game_agent.cognition.npc.engine", "game_agent.memory.store",
             "game_agent.models.llm_http.client", "game_agent.models.embeddings_http", "sqlite3"):
    assert name not in sys.modules, name
if not {module!r}.startswith("cognition.npc"):
    assert "game_agent.cognition.npc" not in sys.modules
if not {module!r}.startswith("models.llm_http"):
    assert "game_agent.models.llm_http" not in sys.modules
'''
    result = subprocess.run([sys.executable, "-c", code],
                            cwd=Path(__file__).resolve().parents[1],
                            env=dict(os.environ, PYTHONPATH=str(
                                Path(__file__).resolve().parents[1] / "src")),
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_lazy_public_exports_preserve_identity_and_discovery():
    import game_agent
    from game_agent.memory import models as memory_model, store as memory
    from game_agent.world import entities as world_model, runtime as world

    scope = {}
    exec("from game_agent import *", scope)
    assert set(game_agent.__all__) <= scope.keys()
    assert set(game_agent.__all__) <= set(dir(game_agent))
    assert scope["World"] is world.World
    assert scope["MemoryRecord"] is memory.MemoryRecord is memory_model.MemoryRecord
    for name in ("Location", "Entity", "Player", "distance", "location_distance"):
        assert scope[name] is getattr(world, name) is getattr(world_model, name)
    with pytest.raises(AttributeError):
        getattr(game_agent, "missing_public_api")


def test_public_memory_record_does_not_load_sqlite():
    result = subprocess.run([sys.executable, "-c", '''
import sys
from game_agent import MemoryRecord
assert MemoryRecord("记忆", 0.0).content == "记忆"
assert "sqlite3" not in sys.modules
assert "game_agent.memory.store" not in sys.modules
'''], cwd=Path(__file__).resolve().parents[1], env=dict(
        os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1] / "src")),
        capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_core_layers_do_not_import_scenarios_runners_or_evaluation():
    import ast
    import importlib.util
    source = Path(__file__).resolve().parents[1] / 'src' / 'game_agent'
    forbidden = ('game_agent.scenarios', 'game_agent.runners', 'game_agent.evaluation')
    violations = []
    for layer in ('world', 'memory', 'cognition', 'models', 'integration'):
        for path in (source / layer).rglob('*.py'):
            parts = path.relative_to(source.parent).with_suffix('').parts
            package = '.'.join(parts[:-1])
            for node in ast.walk(ast.parse(path.read_text())):
                targets = []
                if isinstance(node, ast.Import):
                    targets = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom):
                    base = importlib.util.resolve_name('.' * node.level + (node.module or ''), package) if node.level else (node.module or '')
                    targets = [base, *(base + '.' + alias.name for alias in node.names)]
                for target in targets:
                    if any(target == prefix or target.startswith(prefix + '.') for prefix in forbidden):
                        violations.append(f'{path.relative_to(source)}:{node.lineno}: {target}')
    assert not violations, '\n'.join(violations)
