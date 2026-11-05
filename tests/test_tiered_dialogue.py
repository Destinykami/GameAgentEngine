"""五类记忆的读取策略：普通对话、远期低重要性、未来与关系隔离、预算。"""
from game_agent import HashEmbedder, MemoryRecord, MemoryStore
from game_agent.cognition.dialogue import DialogueManager


class Capture:
    def complete(self, ctx):
        self.context = ctx
        return '当前回答'


def test_casual_turn_uses_working_without_history_or_embedding(monkeypatch):
    store = MemoryStore(HashEmbedder())
    model = Capture()
    try:
        store.add(MemoryRecord('很早以前玩家随口提了红矿石', 1, player_id='P'))
        store.add(MemoryRecord('今天铁匠铺正在开门', 99))
        def forbidden(*args, **kwargs):
            raise AssertionError('普通对话不应查询历史或嵌入')
        monkeypatch.setattr(store, 'search_archive', forbidden)
        monkeypatch.setattr(store, 'retrieve_important', forbidden)
        monkeypatch.setattr(store._embedder, 'embed', forbidden)
        DialogueManager(model, store, {}, 'N').reply('P', '今天天气怎么样', 100)
        assert model.context.extra['memory_mode'] == 'background'
        assert model.context.memories[0]['category'] == 'episodic'
        assert all('layer' not in m for m in model.context.memories)
        assert [m['content'] for m in model.context.memories] == ['今天铁匠铺正在开门']
        assert all(r.last_accessed is None for r in store.all_valid())
    finally:
        store.close()


def test_explicit_recall_finds_old_low_importance_but_not_private_or_future():
    store = MemoryStore(HashEmbedder())
    model = Capture()
    try:
        store.add(MemoryRecord('我随口提过蓝铜矿石', 1, importance=1, player_id='P'))
        store.add(MemoryRecord('Q 的蓝铜矿石秘密', 2, importance=9, player_id='Q'))
        store.add(MemoryRecord('未来的蓝铜矿石事件', 999, importance=9, player_id='P'))
        DialogueManager(model, store, {}, 'N').reply('P', '你还记得蓝铜矿石吗', 100)
        context = model.context
        assert context.extra['memory_mode'] == 'recall'
        assert any(m['content'] == '我随口提过蓝铜矿石' and m['category'] == 'raw_archive'
                   for m in context.memories)
        assert all(m['player_id'] in ('P', None) and m['timestamp'] <= 100
                   for m in context.memories)
        assert all(r.last_accessed is None for r in store.all_valid())
    finally:
        store.close()


def test_usage_does_not_change_category_and_raw_ids_have_separate_namespace():
    from game_agent.cognition.dialogue.policy import fit_budget
    records = [
        {'id': 1, 'category': 'semantic', 'usage': 'recall', 'content': '长期判断'},
        {'id': 1, 'category': 'semantic', 'usage': 'background', 'content': '长期判断'},
        {'id': 1, 'category': 'raw_archive', 'usage': 'recall', 'content': '原话'},
    ]
    result = fit_budget(records)
    assert [m['content'] for m in result] == ['长期判断', '原话']


def test_background_and_recall_use_same_five_categories():
    store = MemoryStore(HashEmbedder())
    try:
        for kind in ('plan', 'reflection', 'identity', 'observation', 'episode'):
            store.add(MemoryRecord('矿石' + kind, 1, type=kind, importance=8, player_id='P'))
        background = store.working_memories('P', 2)
        recalled = store.retrieve_important('矿石', 2, 'P', top_k=8)
        assert {m['category'] for m in background} == {'current_state', 'semantic', 'episodic'}
        assert {m['category'] for m in recalled} == {'current_state', 'semantic', 'episodic'}
        assert all(m['usage'] == 'background' and 'layer' not in m for m in background)
        assert all(m['usage'] == 'recall' and 'layer' not in m for m in recalled)
    finally:
        store.close()


def test_context_is_bounded_and_no_recall_evidence_is_fabricated():
    store = MemoryStore(HashEmbedder())
    model = Capture()
    try:
        for i in range(12):
            store.add(MemoryRecord('不同事件' + str(i) + '矿石' * 700, i,
                                   importance=9, player_id='P'))
        DialogueManager(model, store, {}, 'N').reply('P', '上次矿石的事呢', 20)
        assert sum(len(m['content']) for m in model.context.memories) <= 3000
        assert any(m.get('truncated') for m in model.context.memories)
        assert len(model.context.memories) <= 12
    finally:
        store.close()


def test_current_utterance_cannot_prove_past_and_empty_history_still_calls_model():
    store = MemoryStore(HashEmbedder())
    model = Capture()
    try:
        store.archive_input('你记得我送过蓝铜矿石吗', 100, 'P', kind='dialogue_in')
        DialogueManager(model, store, {}, 'N').reply('P', '你记得我送过蓝铜矿石吗', 100)
        assert model.context.memories == []
        assert '不要编造' in model.context.system
    finally:
        store.close()
