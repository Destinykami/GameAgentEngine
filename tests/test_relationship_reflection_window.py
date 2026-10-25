"""反思编排接入预算；问题原料、证据和原文生命周期分别验证。"""
from game_agent import HashEmbedder, MemoryRecord, MemoryStore
from game_agent.cognition.reflection import ReflectionEngine


class CaptureModel:
    def __init__(self):
        self.materials = []
        self.evidence = []

    def reflection_questions(self, recent):
        self.materials.append(list(recent))
        return ['矿石']

    def reflection_insights(self, evidence, n=5):
        assert n == 3
        self.evidence.append(list(evidence))
        return []


def test_relationship_generation_caps_material_and_evidence_before_model(monkeypatch):
    store = MemoryStore(HashEmbedder())
    model = CaptureModel()
    try:
        for i in range(180):
            store.add(MemoryRecord(f'矿石事件{i}', i, player_id='P', importance=2))
        store.add(MemoryRecord('矿石未来事件', 999, player_id='P'))
        store.add(MemoryRecord('矿石别的玩家', 180, player_id='Q'))
        store.add(MemoryRecord('矿石共享观察', 180))
        count = store.archive_count()
        def forbidden(*args, **kwargs):
            raise AssertionError('问题原料和证据不可走全量 all_valid')
        monkeypatch.setattr(store, 'all_valid', forbidden)
        assert ReflectionEngine(model).reflect_relationship(store, 'P', 200) == []
        assert model.materials == [[f'矿石事件{i}' for i in range(80, 180)]]
        assert len(model.evidence) == 1 and len(model.evidence[0]) <= 10
        assert all('未来' not in content and '共享' not in content and '别的玩家' not in content
                   for _, content in model.evidence[0])
        assert store.archive_count() == count
    finally:
        store.close()


def test_empty_relationship_window_does_not_call_model_or_retrieve():
    store = MemoryStore(HashEmbedder())
    model = CaptureModel()
    try:
        store.add(MemoryRecord('未来事件', 100, player_id='P'))
        store.add(MemoryRecord('共享事件', 1))
        assert ReflectionEngine(model).reflect_relationship(store, 'P', 2) == []
        assert model.materials == model.evidence == []
    finally:
        store.close()


def test_configured_evidence_type_is_preserved_with_observation_materials():
    store = MemoryStore(HashEmbedder())
    model = CaptureModel()
    try:
        store.add(MemoryRecord('矿石观察', 1, player_id='P'))
        episode = store.add(MemoryRecord('矿石情节', 2, player_id='P', type='episode'))
        engine = ReflectionEngine(model, evidence_types=('episode',))
        engine.reflect_relationship(store, 'P', 3)
        assert model.materials == [['矿石观察']]
        assert model.evidence == [[(episode, '矿石情节')]]
        assert all(m.last_accessed is None for m in store.all_valid())
    finally:
        store.close()
