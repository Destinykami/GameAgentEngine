"""独立决策模块只接收上下文与窄依赖，不需要世界或数据库。"""

import pytest

from game_agent.cognition.autonomous import AutonomousDecider, DecisionContext
from game_agent.world.entities import Entity, Location


class _CaptureModel:
    def decide_action(self, *args):
        self.args = args
        return {"action": "talk", "target": "P"}


class _Cognition:
    def has_relationship(self, entity_id):
        return entity_id == "P"

    def trust_toward(self, entity_id):
        assert entity_id == "P"
        return -0.5

    def identity_belief(self):
        return "尊重约定"


@pytest.mark.parametrize("identity_enabled", [False, True])
def test_model_receives_visible_relationships_and_optional_identity(identity_enabled):
    model = _CaptureModel()
    history = ["经过广场"]
    context = DecisionContext(
        "N", "观察局势", {"social": 0.8},
        (Entity("player", "P", Location("L")),
         Entity("player", "陌生人", Location("L"))),
        "基础物理感知", history, "物理状态")
    result = AutonomousDecider().decide(
        model, context, memory_context="共享与可见关系记忆",
        cognition=_Cognition(), use_identity_beliefs=identity_enabled)
    assert result == {"action": "talk", "target": "P"}
    expected = ("基础物理感知 | 自己的记忆: 共享与可见关系记忆"
                " | 对视距内对象的信任度: P -0.50")
    if identity_enabled:
        expected += " | 身份信念: 尊重约定"
    assert model.args == ("N", "观察局势", {"social": 0.8}, expected,
                          history, "物理状态")
    assert model.args[4] is history
