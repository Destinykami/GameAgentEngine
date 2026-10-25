"""世界对话对各 NPC 原文档案的独立回流。"""
import pytest

from game_agent import Location, World
from game_agent.memory.errors import ArchiveWriteError
from tests.test_persistence import _StubLLM


def world(directory):
    w = World('W', [Location('L', 0, 0)])
    for name in ('A', 'B'):
        w.add_npc(name, {}, _StubLLM(), data_dir=str(directory), location='L')
    return w


def test_world_conversation_keeps_actual_original_in_both_npcs(tmp_path):
    w = world(tmp_path)
    try:
        w.advance(1)
        w.execute_action(w.get('A'), {'action': 'talk', 'target': 'B', 'utterance': '  假如有矿石  '})
        a = [r for r in w.npc('A').store.search_archive('', player_id='B')
             if r['kind'].startswith('dialogue_')]
        b = [r for r in w.npc('B').store.search_archive('', player_id='A')
             if r['kind'].startswith('dialogue_')]
        assert {r['content'] for r in a} == {r['content'] for r in b} == {'  假如有矿石  ', 'stub-reply'}
        assert {(r['speaker'], r['kind']) for r in a} == {('A', 'dialogue_out'), ('B', 'dialogue_in')}
        assert {(r['speaker'], r['kind']) for r in b} == {('A', 'dialogue_in'), ('B', 'dialogue_out')}
    finally:
        w.close()


@pytest.mark.parametrize('failed_npc', ['A', 'B'])
def test_archive_failure_is_not_silently_swallowed(tmp_path, monkeypatch, failed_npc):
    w = world(tmp_path)
    def fail(*args, **kwargs):
        raise OSError('disk unavailable')
    monkeypatch.setattr(w.npc(failed_npc).store._archive, 'append', fail)
    try:
        with pytest.raises(ArchiveWriteError, match='disk unavailable'):
            w.execute_action(w.get('A'), {'action': 'talk', 'target': 'B', 'utterance': '原话'})
    finally:
        w.close()
