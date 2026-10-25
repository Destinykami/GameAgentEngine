"""保存失败必须可见；实时库部分提交不冒充完整检查点。"""
import pytest

from game_agent import World, Location, HashEmbedder
from game_agent.world.errors import SaveError
from tests.test_persistence import _StubLLM


@pytest.mark.parametrize('failed', [0, 1, 2])
def test_failed_npc_save_reports_name_and_rolls_back_world(tmp_path, monkeypatch, failed):
    w = World('W', [Location('L', 0, 0)], path=str(tmp_path / 'world.db'))
    try:
        for name in ['A', 'B', 'C']:
            w.add_npc(name, {}, _StubLLM(), data_dir=str(tmp_path))
        w.advance(1)
        w.save()
        w.advance(12)
        npc = w.npc(['A', 'B', 'C'][failed])
        def fail():
            raise OSError('disk failure')
        monkeypatch.setattr(npc, 'save', fail)
        with pytest.raises(SaveError) as caught:
            w.save()
        assert caught.value.stage == 'npc' and caught.value.npc_name == npc.name
        assert isinstance(caught.value.__cause__, OSError)
        restored = World('W', [Location('L', 0, 0)], path=str(tmp_path / 'world.db'))
        try:
            restored.load()
            assert restored.clock == 1
        finally:
            restored.close()
    finally:
        w.close()


def test_world_commit_failure_reports_stage(tmp_path, monkeypatch):
    from contextlib import contextmanager
    from game_agent.world.persistence import WorldStore
    @contextmanager
    def fail(self, *args):
        yield
        raise OSError('commit failed')
    monkeypatch.setattr(WorldStore, 'write_snapshot', fail)
    w = World('W', [Location('L', 0, 0)], path=str(tmp_path / 'world.db'))
    try:
        with pytest.raises(SaveError) as caught:
            w.save()
        assert caught.value.stage == 'world' and caught.value.npc_name is None
        assert isinstance(caught.value.__cause__, OSError)
    finally:
        w.close()


def test_runner_stops_without_success_message_and_closes_world(tmp_path, monkeypatch, capsys):
    from game_agent.runners.inazuma import run
    from game_agent.runners.artifacts import RunPaths
    closed = []
    close = World.close
    def record_close(world):
        closed.append(True)
        close(world)
    def fail(world):
        raise SaveError('world', None, OSError('disk'))
    monkeypatch.setattr(World, 'save', fail)
    monkeypatch.setattr(World, 'close', record_close)
    live = tmp_path / 'live.jsonl'
    with pytest.raises(SaveError):
        run(RunPaths(str(tmp_path / 'run'), str(live)), llm_factory=_StubLLM,
            embedder_factory=HashEmbedder, days=1, moments=[7])
    assert closed == [True]
    assert '世界状态已存' not in capsys.readouterr().out
    assert '__done__' not in live.read_text()
