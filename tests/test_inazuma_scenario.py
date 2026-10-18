"""稻妻·眼狩令 情境测试 (B+ 涌现)。

引擎 (persona_agent/world.py) 保持通用, 只出动作空间+物理规则; "对话谁得什么证据 /
找铁匠是否锻刀 / 执行官收缴持眼者是否算目击" 这些具体世界行为, 由情境层
(examples/world_auto_sim.py) 经 World 的动作效果钩子注入。本测试验证:
1. talk → LLM 从对话生成证据 (新颖性对照 + 文本去重双保险);
2. talk 铁匠 → 锻刀升攻 (与证据独立);
3. help 持眼者 / 执行官收缴持眼者被目击 → 模板证据 (非对话, 不走 LLM);
4. 同一证据重复不新增 + 去重反馈写入历史;
5. 未注册钩子的纯引擎世界, 同样的动作不产生任何世界行为 (引擎与情境解耦)。
无网络, 无真 LLM (用一个返回预设证据的桩代替 LLM.ask)。
"""
from __future__ import annotations

import importlib.util
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from persona_agent.world import World, Location
from tests.test_persistence import _StubLLM


class _AskStub(_StubLLM):
    """在 _StubLLM 上加 ask: 按队列弹出预设证据 (模拟 LLM 从对话生成新证据)。
    队列空时回 NONE (模拟"确无新证据")。"""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self._queue: list[str] = []

    def load_reasons(self, items: list[str]) -> None:
        self._queue = list(items)

    def ask(self, question: str, system: str | None = None, **kw) -> str:
        return self._queue.pop(0) if self._queue else "NONE"


# 以模块方式载入情境 (不跑 main), 取其效果函数与 register_scenario。
_WAS_PATH = os.path.join(os.path.dirname(__file__), "..", "examples", "world_auto_sim.py")
_spec = importlib.util.spec_from_file_location("world_auto_sim", _WAS_PATH)
was = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(was)

LOCATIONS = [Location("主城街道", 0, 0), Location("治疗堂", 1, 0),
             Location("锻造坊", 2, 0), Location("眼狩署", 0, 1),
             Location("神樱庭", 0, 3), Location("城外官道", 5, 5)]


def _world(register: bool = True, llm: _AskStub | None = None) -> tuple[World, _AskStub]:
    w = World("稻妻城", LOCATIONS, path=None)
    llm = llm or _AskStub()
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
    return w, llm


def _last(w: World):
    assert w.visual_events, "应追加了视觉事件"
    return w.visual_events[-1]


def test_talk_generates_reason_from_llm():
    w, llm = _world()
    llm.load_reasons(["桃音证言: 眼狩令下持眼者被迫离散、伤者无依"])
    t = w.get("旅行者")
    t.move(w.locations["治疗堂"])
    w.get("桃音").move(w.locations["治疗堂"])
    w.execute_action(t, {"action": "talk", "target": "桃音", "utterance": "眼狩令之弊?"})
    ve = _last(w)
    assert ve.reason_added == "桃音证言: 眼狩令下持眼者被迫离散、伤者无依"
    assert ve.reason_count == 1
    w.close()


def test_talk_no_new_evidence_yields_none():
    """LLM 回 NONE (确无新证据) → 不新增, 也不报错。"""
    w, llm = _world()
    llm.load_reasons(["NONE"])
    t = w.get("旅行者")
    w.execute_action(t, {"action": "talk", "target": "桃音", "utterance": "还好吗?"})
    ve = _last(w)
    assert not ve.reason_added and len(t.reasons) == 0
    w.close()


def test_talk_blacksmith_forges_weapon_and_reason():
    w, llm = _world()
    llm.load_reasons(["刚郎作证: 收缴神之眼后武器生意断绝"])
    t = w.get("旅行者")
    t.move(w.locations["锻造坊"])   # F3-3: 交互目标必须在视距内
    atk0 = t.attack
    w.execute_action(t, {"action": "talk", "target": "刚郎", "utterance": "锻把武器"})
    ve = _last(w)
    assert ve.reason_added and ve.reason_count == 1
    assert ve.weapon_attack == t.attack and t.attack > atk0
    w.close()


def test_help_vision_holder_gives_template_reason():
    w, llm = _world()
    t = w.get("旅行者")
    t.move(w.locations["治疗堂"])
    w.get("桃音").move(w.locations["治疗堂"])
    w.execute_action(t, {"action": "help", "target": "桃音"})
    ve = _last(w)
    assert ve.reason_added and "藏好神之眼" in ve.reason_added
    w.close()


def test_enforcer_seizing_vision_holder_witness_reason():
    w, llm = _world()
    t = w.get("旅行者")
    for who in ("执行官", "桃音", "旅行者"):
        w.get(who).move(w.locations["眼狩署"])
    w.execute_action(w.get("执行官"), {"action": "attack", "target": "桃音"})
    ve = _last(w)
    assert ve.witnessed and ve.reason_count >= 1
    assert any("目睹" in r for r in t.reasons)
    w.close()


def test_reason_dedup_and_feedback():
    """同一证据重复 (LLM 又给了同一条) → 文本去重兜底, 不新增 + 反馈进历史。"""
    w, llm = _world()
    llm.load_reasons(["桃音证言: 持眼者离散", "桃音证言: 持眼者离散"])
    t = w.get("旅行者")
    t.move(w.locations["治疗堂"])
    w.get("桃音").move(w.locations["治疗堂"])
    w.execute_action(t, {"action": "talk", "target": "桃音", "utterance": "眼狩令之弊?"})
    n1 = len(t.reasons)
    w.execute_action(t, {"action": "talk", "target": "桃音", "utterance": "再说一遍?"})
    assert len(t.reasons) == n1 == 1, "同一证据不应重复新增"
    assert any("重复" in h for h in t.history), "应有去重反馈进历史"
    w.close()


def test_unregistered_engine_has_no_world_behavior():
    """未注册情境钩子: 引擎只出物理/对话, 不产生任何稻妻世界行为。"""
    w, llm = _world(register=False)
    llm.load_reasons(["不该出现的证据"])
    t = w.get("旅行者")
    w.execute_action(t, {"action": "talk", "target": "桃音", "utterance": "眼狩令之弊?"})
    ve = _last(w)
    assert ve.type == "conversation"
    assert not ve.reason_added and t.attack == 12, "纯引擎不应得证据/锻刀"
    w.close()
