"""稻妻·眼狩令 情境测试。

引擎 (persona_agent/world.py) 保持通用, 只出动作空间+物理规则; "对话谁得什么理由 /
找铁匠是否锻刀 / 执行官收缴持眼者是否算目击" 这些具体世界行为, 由情境层
(examples/world_auto_sim.py) 经 World 的动作效果钩子注入。本测试验证:
1. 注册钩子后, 稻妻世界行为生效 (healer/blacksmith 得理由、blacksmith 锻刀升攻、
   帮持眼者得理由、执行官收缴持眼者→目击者得理由);
2. 理由去重 (同一理由不重复新增) + 去重反馈写入历史;
3. 未注册钩子的纯引擎世界, 同样的动作不产生任何世界行为 (引擎与情境解耦)。
无网络, 无真 LLM (本阶段理由为固定映射, 不触发 LLM 生成)。
"""
from __future__ import annotations

import importlib.util
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from persona_agent.world import World, Location
from tests.test_persistence import _StubLLM

# 以模块方式载入情境 (不跑 main), 取其效果函数与 register_scenario。
_WAS_PATH = os.path.join(os.path.dirname(__file__), "..", "examples", "world_auto_sim.py")
_spec = importlib.util.spec_from_file_location("world_auto_sim", _WAS_PATH)
was = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(was)

LOCATIONS = [Location("主城街道", 0, 0), Location("治疗堂", 1, 0),
             Location("锻造坊", 2, 0), Location("眼狩署", 0, 1),
             Location("神樱庭", 0, 3), Location("城外官道", 5, 5)]


def _world(register: bool = True) -> World:
    w = World("稻妻城", LOCATIONS, path=None)
    llm = _StubLLM()
    for name, role, loc in [("桃音", "vision_holder,healer", "治疗堂"),
                            ("刚郎", "blacksmith", "锻造坊"),
                            ("小梅", "scholar,vision_holder", "主城街道"),
                            ("执行官", "enforcer", "眼狩署"),
                            ("雷电将军", "shogun", "神樱庭")]:
        w.add_npc(name, {"social": 0.5, "goal_oriented": 0.5}, llm=llm,
                  data_dir=tempfile.mkdtemp(), location=loc)
        w.get(name).role = role
        w.get(name).health = 300
    w.add_agent_player("旅行者", "主城街道", "x", llm=llm,
                       health=300, attack=12, defense=5)
    if register:
        was.register_scenario(w)
    return w


def _last(w: World):
    assert w.visual_events, "应追加了视觉事件"
    return w.visual_events[-1]


def test_talk_healer_gives_reason():
    w = _world()
    t = w.get("旅行者")
    t.move(w.locations["治疗堂"])
    w.get("桃音").move(w.locations["治疗堂"])
    w.execute_action(t, {"action": "talk", "target": "桃音", "utterance": "眼狩令之弊?"})
    ve = _last(w)
    assert ve.reason_added and "桃音" in ve.reason_added and ve.reason_count == 1
    w.close()


def test_talk_scholar_and_blacksmith_reason_and_weapon():
    w = _world()
    t = w.get("旅行者")
    # 小梅 (scholar) → 典籍理由
    w.execute_action(t, {"action": "talk", "target": "小梅", "utterance": "孤本里怎么说?"})
    ve = _last(w)
    assert ve.reason_added and ve.reason_count == 1
    # 刚郎 (blacksmith) → 铁匠理由 + 锻刀升攻
    atk0 = t.attack
    w.execute_action(t, {"action": "talk", "target": "刚郎", "utterance": "锻把武器"})
    ve = _last(w)
    assert ve.reason_added and ve.reason_count == 2
    assert ve.weapon_attack == t.attack and t.attack > atk0
    w.close()


def test_help_vision_holder_gives_reason():
    w = _world()
    t = w.get("旅行者")
    t.move(w.locations["治疗堂"])
    w.get("桃音").move(w.locations["治疗堂"])
    w.execute_action(t, {"action": "help", "target": "桃音"})
    ve = _last(w)
    assert ve.reason_added and "藏好神之眼" in ve.reason_added
    w.close()


def test_enforcer_seizing_vision_holder_witness_reason():
    w = _world()
    t = w.get("旅行者")
    # 执行官、桃音(持眼者)、旅行者同处一地; 执行官收缴 → 旅行者目击得理由
    for who in ("执行官", "桃音", "旅行者"):
        w.get(who).move(w.locations["眼狩署"])
    w.execute_action(w.get("执行官"), {"action": "attack", "target": "桃音"})
    ve = _last(w)
    assert ve.witnessed and ve.reason_count >= 1
    assert any("目睹" in r for r in t.reasons)
    w.close()


def test_reason_dedup_and_feedback():
    w = _world()
    t = w.get("旅行者")
    t.move(w.locations["治疗堂"])
    w.get("桃音").move(w.locations["治疗堂"])
    w.execute_action(t, {"action": "talk", "target": "桃音", "utterance": "眼狩令之弊?"})
    n1 = len(t.reasons)
    # 重复找桃音取同一条理由 → 不新增, 且写入历史提示
    w.execute_action(t, {"action": "talk", "target": "桃音", "utterance": "再说一遍?"})
    assert len(t.reasons) == n1, "同一理由不应重复新增"
    assert any("已重复" in h for h in t.history), "应有去重反馈进历史"
    w.close()


def test_unregistered_engine_has_no_world_behavior():
    """未注册情境钩子: 引擎只出物理/对话, 不产生任何稻妻世界行为。"""
    w = _world(register=False)
    t = w.get("旅行者")
    w.execute_action(t, {"action": "talk", "target": "桃音", "utterance": "眼狩令之弊?"})
    ve = _last(w)
    assert ve.type == "conversation"
    assert not ve.reason_added and t.attack == 12, "纯引擎不应得理由/锻刀"
    w.close()
