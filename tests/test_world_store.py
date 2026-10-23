"""世界存储边界：保存失败不留下半份世界快照，不需要认知或模型。"""

import pytest

from game_agent.world.entities import Entity, Location
from game_agent.world.persistence import WorldStore


def test_failed_snapshot_write_rolls_back_entities_and_metadata(tmp_path):
    store = WorldStore(str(tmp_path / "world.db"))
    original = Entity("npc", "A", Location("L"), health=60)
    with store.write_snapshot([original], {"clock": 7.0}):
        pass

    with pytest.raises(RuntimeError, match="保存中断"):
        with store.write_snapshot(
                [Entity("player", "B", Location("R"))], {"clock": 9.0}):
            raise RuntimeError("保存中断")

    with store.read_snapshot() as snapshot:
        assert [(e.name, e.health) for e in snapshot.entities] == [("A", 60)]
        assert snapshot.metadata["clock"] == 7.0
    store.close()
