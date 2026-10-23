"""对话窄接口、访问副作用与独立轮流发言的契约。"""

import pytest

from game_agent.cognition.dialogue import DialogueManager, two_agent_exchange


def test_reply_uses_narrow_ports_and_preserves_context_and_trait_reference():
    memories = [{"id": 1, "content": "共享记忆", "player_id": None}]
    events = []

    class Memory:
        def retrieve(self, **options):
            events.append(("retrieve", options))
            return memories

    class Model:
        def complete(self, ctx):
            events.append(("complete", ctx))
            return "回答"

    traits = {"social": 0.5}
    manager = DialogueManager(Model(), Memory(), traits, "桃音")
    traits["social"] = 0.9
    assert manager.reply("Aria", "  你好  ", 3.0, top_k=3) == "回答"
    assert events[0] == ("retrieve", {
        "query": "  你好   (对话者: Aria)", "now": 3.0, "top_k": 3,
        "player_id": "Aria", "include_player": "Aria",
        "include_shared": True, "min_relevance": 0.1,
    })
    ctx = events[1][1]
    assert ctx.system == (
        "你是 桃音。记忆流里出现的 桃音 就是你本人, "
        "开口时一律用'我', 不要在自己的话里用名字称呼自己。"
        "只基于你记得的事情回答。人格特质: {'social': 0.9}")
    assert ctx.player_id == "Aria"
    assert ctx.question == "  你好  "
    assert ctx.memories is memories
    assert ctx.extra == {}


def test_model_failure_keeps_retrieval_access_time_without_observation_writes():
    from game_agent import HashEmbedder, MemoryRecord, MemoryStore

    class Model:
        def complete(self, ctx):
            raise RuntimeError("generation failed")

    store = MemoryStore(HashEmbedder())
    store.add(MemoryRecord(content="Aria 帮我修咖啡机", timestamp=0.0,
                           player_id="Aria"))
    manager = DialogueManager(Model(), store, {}, "桃音")
    try:
        with pytest.raises(RuntimeError, match="generation failed"):
            manager.reply("Aria", "咖啡机", 2.0)
        records = store.all_valid()
        assert len(records) == 1
        assert records[0].last_accessed == 2.0
    finally:
        store.close()


def test_retrieval_failure_does_not_call_model():
    class Memory:
        def retrieve(self, **options):
            raise RuntimeError("retrieval failed")

    class Model:
        def complete(self, ctx):
            raise AssertionError("The model must not be called")

    manager = DialogueManager(Model(), Memory(), {}, "桃音")
    with pytest.raises(RuntimeError, match="retrieval failed"):
        manager.reply("Aria", "你好", 1.0)


def test_exchange_uses_reply_ports_in_order_at_same_time_without_opener_entry():
    calls = []

    class Speaker:
        def __init__(self, name):
            self.name = name
            self.count = 0

        def reply(self, player_id, utterance, now):
            self.count += 1
            calls.append((self.name, player_id, utterance, now))
            return f"{self.name}{self.count}"

    assert DialogueManager.two_agent_exchange is two_agent_exchange
    transcript = two_agent_exchange(Speaker("A"), "甲", Speaker("B"), "乙",
                                    "开场", 4.0)
    assert transcript == [
        {"speaker": "甲", "utterance": "A1"},
        {"speaker": "乙", "utterance": "B1"},
        {"speaker": "甲", "utterance": "A2"},
        {"speaker": "乙", "utterance": "B2"},
    ]
    assert calls == [("A", "乙", "开场", 4.0), ("B", "甲", "A1", 4.0),
                     ("A", "乙", "B1", 4.0), ("B", "甲", "A2", 4.0)]


@pytest.mark.parametrize("rounds", [0, -1])
def test_exchange_without_rounds_does_not_call_speakers(rounds):
    class Speaker:
        def reply(self, **kwargs):
            raise AssertionError("No turn should run")

    assert two_agent_exchange(Speaker(), "甲", Speaker(), "乙", "开场", 1.0,
                              rounds=rounds) == []


def test_exchange_forwards_empty_reply_and_stops_on_next_failure():
    calls = []

    class First:
        def reply(self, **options):
            calls.append(("A", options))
            return ""

    class Second:
        def reply(self, **options):
            calls.append(("B", options))
            raise RuntimeError("second speaker failed")

    with pytest.raises(RuntimeError, match="second speaker failed"):
        two_agent_exchange(First(), "甲", Second(), "乙", "开场", 2.0)
    assert calls == [
        ("A", {"player_id": "乙", "utterance": "开场", "now": 2.0}),
        ("B", {"player_id": "甲", "utterance": "", "now": 2.0}),
    ]
