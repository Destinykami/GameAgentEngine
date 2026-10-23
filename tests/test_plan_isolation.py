"""计划 context 与重规划中断的面隔离回归 (F1-5)。

日计划/重规划的世界背景只取共享流观察; "计划被打断: 被 X 攻击了"这类含玩家名
的观察写进被中断者的关系面, 不进共享流。
"""

from __future__ import annotations



from game_agent import NPC
from game_agent.models.embeddings import HashEmbedder
from tests.test_persistence import _StubLLM, TRAITS


class _CapturePlan(_StubLLM):
    def __init__(self) -> None:
        super().__init__()
        self.contexts = []

    def generate_plan(self, persona_traits, previous_day, date, context=""):
        self.contexts.append(context)
        return super().generate_plan(persona_traits, previous_day, date, context)


def _npc() -> tuple[NPC, _CapturePlan]:
    llm = _CapturePlan()
    npc = NPC("测试人", dict(TRAITS), llm=llm, embedder=HashEmbedder())
    npc.observe("Aria 悄悄告诉我: 她把神之眼藏在神樱树下", 1.0,
                player_id="Aria")
    npc.observe("雷电将军颁布眼狩令: 全城神之眼一律收缴", 2.0)
    return npc, llm


def test_daily_plan_context_only_shared_stream():
    npc, llm = _npc()
    npc.generate_daily_plan("", "d", 8.0)
    ctx = llm.contexts[-1]
    assert "神樱树下" not in ctx, "玩家的私有观察不得进入共享 plan 生成上下文"
    assert "眼狩令" in ctx, "共享世界背景仍应进入计划上下文"


def test_replan_context_only_shared_stream():
    npc, llm = _npc()
    npc.replan(10.0, "被 Aria 攻击了")
    ctx = llm.contexts[-1]
    assert "神樱树下" not in ctx, "重规划 context 不得含玩家私有观察"
    assert "眼狩令" in ctx, "重规划仍应在世界背景下生成"


def test_replan_interruption_goes_to_actor_stream_not_shared():
    npc, _llm = _npc()
    npc.replan(10.0, "被 Aria 攻击了", interruption_player="Aria")
    aria_obs = npc.store.all_valid(player_id="Aria", types=["observation"])
    shared_obs = npc.store.all_valid(shared=True, types=["observation"])
    assert any("计划被打断" in m.content and "Aria" in m.content
               for m in aria_obs), "中断观察应写进攻击者的关系面"
    assert not any("计划被打断" in m.content for m in shared_obs), \
        "含玩家名的中断观察不得进入共享流"
