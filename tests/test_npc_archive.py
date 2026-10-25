"""观察、原话、感知和生成失败的归档与补处理契约。"""
import pytest

from game_agent import NPC
from tests.test_persistence import _StubLLM


def test_duplicate_observations_keep_every_original_and_link_once():
    npc = NPC('N', {}, _StubLLM())
    try:
        first = npc.observe('相同的真实经历', 1, 'P')
        assert npc.observe('相同的真实经历', 8, 'P') == first
        assert npc.store.archive_count() == 2 and npc.memory_count() == 1
        assert len(npc.store.source_refs(first)) == 2
        before = npc.store.all_valid()[0].importance
        assert npc.retry_pending_memories() == {'completed': [], 'failed': []}
        assert npc.store.all_valid()[0].importance == before
    finally:
        npc.store.close()


def test_failed_score_keeps_original_and_retries_after_restart(tmp_path):
    class Model(_StubLLM):
        def score_importance(self, *args):
            raise RuntimeError('score failed')
    npc = NPC.create('N', {}, Model(), data_dir=str(tmp_path))
    with pytest.raises(RuntimeError, match='score failed'):
        npc.observe('应当保存的共享事件', 2)
    assert npc.memory_count() == 0
    source = npc.store.pending_archive()[0]
    assert source.content == '应当保存的共享事件'
    npc.store.close()
    restored = NPC.load(str(tmp_path / 'N.db'), _StubLLM())
    try:
        assert len(restored.retry_pending_memories()['completed']) == 1
        assert restored.memory_count() == restored.store.archive_count() == 1
        assert restored.runtime_state().importance_accum == 5
        assert restored.retry_pending_memories()['completed'] == []
    finally:
        restored.store.close()


def test_perception_failure_preserves_exact_utterance_for_retry():
    class Model(_StubLLM):
        failed = True
        def perceive_action(self, *args):
            if self.failed:
                raise RuntimeError('perception failed')
            return 'P 提出了一个假设'
    model = Model()
    npc = NPC('N', {}, model)
    try:
        with pytest.raises(RuntimeError, match='perception'):
            npc.perceive_action('P', '对TA说:  假如我有矿石呢？ ', 1)
        source = npc.store.pending_archive()[0]
        assert source.content == ' 假如我有矿石呢？ '
        assert source.kind == 'dialogue_in' and source.speaker == 'P'
        model.failed = False
        assert npc.retry_pending_memories()['failed'] == []
        assert npc.store.all_valid()[0].content == 'P 提出了一个假设'
        assert npc.store.read_archive(source.id, player_id='P').content == source.content
    finally:
        npc.store.close()


def test_generation_failure_retains_input_without_inventing_reply():
    class Model(_StubLLM):
        def complete(self, ctx):
            raise RuntimeError('generation failed')
    npc = NPC('N', {}, Model())
    try:
        with pytest.raises(RuntimeError, match='generation failed'):
            npc.speak('P', '  随口说的话  ', 2)
        raw = npc.store.pending_archive()
        assert len(raw) == 1 and raw[0].content == '  随口说的话  '
        assert raw[0].kind == 'dialogue_in' and npc.memory_count() == 0
        assert npc.retry_pending_memories()['failed'] == []
        assert npc.memory_count() == 1 and npc.store.archive_count() == 1
    finally:
        npc.store.close()


def test_speak_records_exact_raw_and_preserves_recording_switches():
    npc = NPC('N', {}, _StubLLM())
    try:
        npc.speak('P', '你好', 1, remember=False)
        assert npc.store.archive_count() == 0
        reply = npc.speak('P', '你好', 2)
        rows = npc.store.search_archive('', player_id='P')
        assert {r['content'] for r in rows} == {'你好', reply}
        assert {r['speaker'] for r in rows} == {'P', 'N'}
        assert len({r['session_id'] for r in rows}) == 1
        before = npc.store.archive_count()
        npc.speak('P', '已经由上游保存', 3, record_utterance=False)
        new = npc.store.search_archive('', player_id='P', after=3)
        assert all(r['kind'] != 'dialogue_in' for r in new)
        assert npc.store.archive_count() >= before + 1
    finally:
        npc.store.close()


def test_dialogue_reflow_keeps_actual_speaker_and_original():
    npc = NPC('A', {}, _StubLLM())
    try:
        npc.remember_dialogue('B', '我只是开个玩笑', 1, speaker='A')
        npc.remember_dialogue('B', '知道了', 1, speaker='B')
        rows = npc.store.search_archive('', player_id='B')
        assert {(r['speaker'], r['content']) for r in rows} == {
            ('A', '我只是开个玩笑'), ('B', '知道了')}
        assert {r['kind'] for r in rows} == {'dialogue_in', 'dialogue_out'}
    finally:
        npc.store.close()
