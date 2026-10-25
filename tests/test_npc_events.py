"""NPC 的结构化元数据来自确定的入口上下文，不靠模型猜测。"""
import pytest

from game_agent import NPC
from game_agent.memory import EventContext, EventQuery, EventScope
from tests.test_persistence import _StubLLM


def test_direct_dialogue_has_two_directions_originals_and_no_assumed_location():
    npc = NPC('N', {}, _StubLLM())
    try:
        reply = npc.speak('P', '  如果我送你矿石呢？ ', 1)
        scope = EventScope(player_id='P', as_of=1)
        events = npc.store.query_events(scope, EventQuery(participants=('P', 'N'))).events
        assert len(events) == 2
        incoming, outgoing = events
        assert (incoming.actor, incoming.target) == ('P', 'N')
        assert (outgoing.actor, outgoing.target) == ('N', 'P')
        assert incoming.occurred_at == incoming.observed_at == 1
        assert incoming.location is None and incoming.evidence_kind == 'utterance'
        assert incoming.session_id == outgoing.session_id
        assert npc.store.read_event_source(incoming.source_id, scope).content == '  如果我送你矿石呢？ '
        assert npc.store.read_event_source(outgoing.source_id, scope).content == reply
        assert npc.store.count_events(scope, EventQuery(evidence_kinds=('observation',))) == 0
    finally:
        npc.store.close()


def test_action_attempt_is_queryable_before_failed_perception():
    class Fail(_StubLLM):
        def perceive_action(self, *args):
            raise RuntimeError('perception failed')
    npc = NPC('N', {}, Fail())
    try:
        with pytest.raises(RuntimeError, match='perception failed'):
            npc.perceive_action('P', '尝试把箱子搬走', 5)
        scope = EventScope(player_id='P', as_of=5)
        event = npc.store.query_events(scope).events[0]
        assert event.evidence_kind == 'action_attempt'
        assert (event.actor, event.target, event.participants) == ('P', 'N', ('N', 'P'))
        assert event.occurred_at == event.observed_at == 5
        assert npc.store.read_event_source(event.source_id, scope).state == 'pending'
        assert npc.memory_count() == 0
    finally:
        npc.store.close()


def test_explicit_context_survives_failed_projection_restart_and_retry(tmp_path):
    class Fail(_StubLLM):
        def score_importance(self, *args):
            raise RuntimeError('score failed')
    npc = NPC.create('N', {}, Fail(), data_dir=str(tmp_path))
    context = EventContext(event_type='gift', occurred_at=2, actor='P', target='N',
        participants=('见证者',), location='码头', evidence_kind='observation')
    with pytest.raises(RuntimeError, match='score failed'):
        npc.observe('P 在码头送出了矿石', 8, 'P', event=context)
    scope = EventScope(player_id='P', as_of=8)
    before = npc.store.query_events(scope).events[0]
    npc.store.close()
    restored = NPC.load(str(tmp_path / 'N.db'), _StubLLM())
    try:
        assert len(restored.retry_pending_memories()['completed']) == 1
        assert restored.store.query_events(scope).events == (before,)
        assert before.location == '码头' and before.participants == ('N', 'P', '见证者')
        assert (before.occurred_at, before.observed_at) == (2, 8)
        assert restored.store.count_events(EventScope(player_id='P', as_of=3)) == 0
    finally:
        restored.store.close()


def test_report_and_free_text_observation_do_not_guess_event_facts():
    npc = NPC('N', {}, _StubLLM())
    try:
        npc.observe('P 告诉我 Q 昨晚在码头送了礼物', 8, 'Q', hearsay=True, hop=1)
        npc.observe('码头下起雨了', 9)
        report = npc.store.query_events(EventScope(player_id='Q', as_of=9)).events[0]
        observation = npc.store.query_events(EventScope(as_of=9)).events[0]
        assert report.evidence_kind == 'report' and report.hearsay and report.hop == 1
        assert report.occurred_at is report.actor is report.target is report.location is None
        assert report.participants == ()  # 关系流 Q 不等于事件参与者
        assert report.observed_at == 8
        assert observation.evidence_kind == 'observation'
        assert observation.location is observation.occurred_at is None
    finally:
        npc.store.close()


def test_dialogue_reflow_and_recording_switches_keep_event_count():
    npc = NPC('N', {}, _StubLLM())
    try:
        npc.speak('P', '不记录', 1, remember=False)
        assert npc.store.count_events(EventScope(player_id='P', as_of=10)) == 0
        npc.remember_dialogue('P', '上游记录的来话', 2, speaker='P')
        npc.speak('P', '上游记录的来话', 2, record_utterance=False)
        scope = EventScope(player_id='P', as_of=10)
        assert npc.store.count_events(scope, EventQuery(event_types=('dialogue_in',))) == 1
        assert npc.store.count_events(scope, EventQuery(event_types=('dialogue_out',))) == 1
        last = npc.store.query_events(scope, EventQuery(descending=True), limit=1).events[0]
        assert last.actor == 'N' and last.target == 'P'
    finally:
        npc.store.close()
