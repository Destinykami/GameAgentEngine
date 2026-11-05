"""对话使用统一检索入口，保留预算、来源与隔离契约。"""
import math

import pytest

from game_agent import MemoryRecord, MemoryStore
from game_agent.memory import EventContext, HybridResult
from game_agent.cognition.dialogue import DialogueManager
from game_agent.cognition.dialogue.policy import fit_budget, needs_history
from tests.test_hybrid_retrieval import ToyEmbedder


class Capture:
    def complete(self, ctx):
        self.context = ctx
        return '回答'


@pytest.mark.parametrize('question', ['那件事怎么样了？', '我们第100次见面做了什么？', '今天天气怎么样？'])
def test_information_requests_use_hybrid_even_without_recall_keyword(question):
    calls = []
    class Memory:
        def working_memories(self, *args, **options):
            return []
        def hybrid_retrieve(self, query, scope, **options):
            calls.append((query, scope, options))
            return HybridResult((), {'dense_complete': False, 'errors': ['partial']})
    model = Capture()
    DialogueManager(model, Memory(), {}, 'N').reply('P', question, 10**12)
    assert calls[0][0] == question
    assert calls[0][1].player_id == 'P' and calls[0][1].include_shared
    assert calls[0][1].as_of == math.nextafter(10**12, -math.inf)
    assert calls[0][2] == {'top_k': 8, 'candidate_k': 32, 'neighbor_radius': 1}
    assert model.context.extra['retrieval']['dense_complete'] is False
    assert model.context.question == question


@pytest.mark.parametrize('greeting', ['', ' 你好！ ', '谢谢', 'hello', '别翻旧账'])
def test_explicit_greetings_and_no_history_requests_skip_retrieval(greeting):
    assert not needs_history(greeting)


def test_semantic_raw_recall_is_not_limited_to_recent_important_records():
    store = MemoryStore(ToyEmbedder())
    model = Capture()
    try:
        store.add(MemoryRecord('feline resting at harbor', 1, player_id='P', importance=1))
        store.add(MemoryRecord('Q feline secret', 2, player_id='Q'))
        store.archive_input('feline game secret', 2, 'P', event=EventContext(instance_id='game'))
        DialogueManager(model, store, {}, 'N').reply('P', '猫咪在哪里', 100)
        contents = [m['content'] for m in model.context.memories]
        assert contents == ['feline resting at harbor']
        assert model.context.extra['retrieval']['route_hits']['dense'] == 1
        assert all(r.last_accessed is None for r in store.all_valid())
    finally:
        store.close()


def test_source_dedup_and_neighbor_priority_respect_budget():
    raw = {'id': 's', 'archive_id': 'a', 'category': 'raw_archive', 'content': '原话'}
    derived = {'id': 1, 'category': 'episodic', 'content': '同一观察',
               'source_refs': [{'archive_id': 'a', 'source_id': 's'}]}
    other = {'id': 2, 'category': 'semantic', 'content': '关系判断', 'source_refs': []}
    assert [m['content'] for m in fit_budget([raw, derived, other])] == ['原话', '关系判断']
    # 原文没有进入预算时，不应因为仅在候选中出现而丢弃派生背景。
    assert fit_budget([dict(raw, content=''), derived])[0]['content'] == '同一观察'
    # 只命中来源的一小段，不能据此抹掉含有额外信息的观察背景。
    partial = dict(raw, truncated=True)
    assert len(fit_budget([partial, derived])) == 2


def test_embedding_failure_still_provides_lexical_evidence_and_diagnostics():
    emb = ToyEmbedder()
    store = MemoryStore(emb)
    model = Capture()
    try:
        store.archive_input('kitten 已经回来了', 1, 'P')
        emb.fail = True
        DialogueManager(model, store, {}, 'N').reply('P', 'kitten 怎么样了', 100)
        assert model.context.memories[0]['content'] == 'kitten 已经回来了'
        assert model.context.extra['retrieval']['errors']
        assert not model.context.extra['retrieval']['dense_complete']
    finally:
        store.close()
