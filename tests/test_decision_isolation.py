"""自治决策上下文的可见对象过滤回归 (F1-6)。

NPC 的决策记忆上下文只包含共享流 + 视距内实体的关系记忆; 视距外玩家的私有
记忆不得进入本次决策 (否则 B 会基于 A 的秘密做决定)。
"""

from __future__ import annotations



from game_agent import Location, MemoryRecord, World
from tests.test_persistence import _StubLLM, TRAITS


class _CaptureDecision(_StubLLM):
    def __init__(self) -> None:
        super().__init__()
        self.perceptions = []

    def decide_action(self, agent_name, goal, persona_traits, perception,
                      history, state):
        self.perceptions.append(perception)
        return super().decide_action(agent_name, goal, persona_traits,
                                     perception, history, state)


def test_decision_context_excludes_out_of_sight_player(tmp_path):
    w = World("w", [Location("近", 0, 0), Location("远", 100, 100)])
    cap = _CaptureDecision()
    w.add_npc("B", dict(TRAITS), llm=cap, data_dir=str(tmp_path / "B"),
              location="近")
    # F5-1 之前的临时注册: 本用例只验证决策上下文过滤。
    w._agent_llms["B"] = cap
    w._agent_personas["B"] = dict(TRAITS)
    w.add_player("P", "远")
    b = w.npc("B")
    b.observe("P 悄悄告诉我: 他把神之眼藏在神樱树下", 1.0, player_id="P")
    b.observe("雷电将军颁布眼狩令: 全城神之眼一律收缴", 2.0)
    w.step_autonomous(3.0)
    perception = cap.perceptions[-1]
    assert "神樱树下" not in perception, \
        "视距外玩家的私有记忆不得进入决策上下文"
    assert "眼狩令" in perception, "共享世界事件仍应进入决策上下文"
    w.close()


def test_all_visible_relationships_are_allowed_but_leaving_and_dead_are_excluded(tmp_path):
    w = World("w", [Location("近"), Location("远", 100, 100)])
    cap = _CaptureDecision()
    npc = w.add_npc("N", dict(TRAITS), llm=cap, autonomous=True,
                    data_dir=str(tmp_path / "N"), location="近")
    w.add_player("P1", "近")
    p2 = w.add_player("P2", "近")
    w.add_player("远方对象", "远")
    dead = w.add_player("死亡对象", "近")
    dead.dead = True
    for i, (entity_id, content) in enumerate([
            (None, "共享契约记录"), ("P1", "P1关系契约记录"),
            ("P2", "P2关系契约记录"), ("远方对象", "远方关系秘密"),
            ("死亡对象", "死亡对象关系秘密")]):
        npc.store.add(MemoryRecord(content, float(i), player_id=entity_id))

    w.step_autonomous(5.0)
    first = cap.perceptions[-1]
    assert "共享契约记录" in first
    assert "P1关系契约记录" in first and "P2关系契约记录" in first
    assert "远方关系秘密" not in first and "死亡对象关系秘密" not in first

    p2.move(w.locations["远"])
    w.step_autonomous(6.0)
    second = cap.perceptions[-1]
    assert "共享契约记录" in second and "P1关系契约记录" in second
    assert "P2关系契约记录" not in second
    w.close()
