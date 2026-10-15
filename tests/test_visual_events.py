"""结构化视觉事件 (单一事实源) 测试。

execute_action / world_event 产出 VisualEvent, 显示字符串由 describe() 派生。
断言: 每种动作类型的事件字段正确、派生字符串与旧 execute_action 逐字一致、
to_dict() 可 JSON 序列化且失败动作不带成功态字段、step_autonomous 每步重置缓冲。
无网络, 无真 LLM。
"""
from __future__ import annotations

import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from persona_agent.world import World, Location
from tests.test_persistence import _StubLLM

LOCATIONS = [Location("主城街道", 0, 0), Location("治疗堂", 1, 0),
             Location("锻造坊", 2, 0), Location("眼狩署", 0, 1),
             Location("神樱庭", 0, 3), Location("城外官道", 5, 5)]


def _world() -> World:
    w = World("稻妻城", LOCATIONS, path=None)   # 内存世界, 不落库
    llm = _StubLLM()
    for name, role, loc in [("桃音", "vision_holder,healer", "治疗堂"),
                            ("刚郎", "blacksmith", "锻造坊"),
                            ("执行官", "enforcer", "眼狩署"),
                            ("雷电将军", "shogun", "神樱庭")]:
        w.add_npc(name, {"social": 0.5, "goal_oriented": 0.5}, llm=llm,
                  data_dir=tempfile.mkdtemp(), location=loc)
        w.get(name).role = role
        w.get(name).health = 300
    w.add_agent_player("旅行者", "主城街道", "x", llm=llm,
                       health=300, attack=12, defense=5)
    w.clock = 14.0
    return w


def _last(w: World):
    assert w.visual_events, "应追加了视觉事件"
    return w.visual_events[-1]


def test_move_success_and_failure():
    w = _world()
    t = w.get("旅行者")
    s = w.execute_action(t, {"action": "move", "dest": "治疗堂"})
    ve = _last(w)
    assert ve.type == "move" and ve.to == "治疗堂" and ve.success
    assert s == "旅行者 移动到 治疗堂" and ve.describe() == s

    s = w.execute_action(t, {"action": "move", "dest": "不存在"})
    ve = _last(w)
    assert ve.success is False and "to" in ve.to_dict()
    assert s == "旅行者 想移动到不存在的 不存在, 未动"
    w.close()


def test_talk_structured_conversation():
    """引擎只管对话的 VisualEvent 结构; 理由/锻刀等世界行为由情境钩子注入 (见 test_inazuma_scenario)。"""
    w = _world()
    t = w.get("旅行者")
    s = w.execute_action(t, {"action": "talk", "target": "桃音",
                             "utterance": "你知道眼狩令造成了什么吗？"})
    ve = _last(w)
    assert ve.type == "conversation" and ve.target == "桃音"
    assert ve.utterance == "你知道眼狩令造成了什么吗？"
    assert ve.reply_speaker == "桃音" and ve.reply
    assert "旅行者 对 桃音 说:" in s and "← 桃音:" in s and ve.describe() == s
    d = ve.to_dict()
    assert d["type"] == "conversation" and d["reply_speaker"] == "桃音"
    json.dumps(d, ensure_ascii=False)   # 可序列化
    # 未注册情境钩子 → 无世界行为 (无理由/不锻刀): 引擎保持通用
    assert not ve.reason_added and t.attack == 12
    w.close()


def test_attack_death_and_atomic_failure():
    w = _world()
    t = w.get("旅行者")
    t.attack = 50
    # 致死
    w.get("桃音").health = 1
    s = w.execute_action(t, {"action": "attack", "target": "桃音"})
    ve = _last(w)
    assert ve.type == "attack" and ve.target_dead and ve.damage >= 0
    assert s == f"旅行者 攻击 桃音, 造成 {ve.damage} 伤害 → 桃音 阵亡!"
    assert ve.to_dict()["target_dead"] is True and ve.to_dict()["damage"] == ve.damage
    # 非致死
    s = w.execute_action(t, {"action": "attack", "target": "雷电将军"})
    ve = _last(w)
    assert ve.target_dead is False
    assert s == f"旅行者 攻击 雷电将军, 造成 {ve.damage} 伤害"
    # 认知失败 → 原子中止, 不带成功态字段
    w.npc("雷电将军").perceive_action = \
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
    s = w.execute_action(t, {"action": "attack", "target": "雷电将军"})
    ve = _last(w)
    assert ve.success is False and "damage" not in ve.to_dict()
    assert "但认知事件生成失败, 动作中止" in s
    w.close()


def test_flee_help_hide_wait():
    w = _world()
    t = w.get("旅行者")
    # flee: 同区域有威胁
    w.get("执行官").move(w.locations["神樱庭"])
    t.move(w.locations["神樱庭"])
    s = w.execute_action(t, {"action": "flee"})
    ve = _last(w)
    assert ve.type == "flee" and ve.to
    assert s == f"旅行者 逃离威胁, 逃到 {ve.to}"
    # help: 引擎只管 help 的 VisualEvent; "帮持眼者→得理由"是情境钩子 (见 test_inazuma_scenario)
    t.move(w.locations["治疗堂"])
    w.get("桃音").move(w.locations["治疗堂"])
    s = w.execute_action(t, {"action": "help", "target": "桃音"})
    ve = _last(w)
    assert ve.type == "help" and not ve.reason_added
    assert s == "旅行者 帮助 桃音"
    # hide
    s = w.execute_action(t, {"action": "hide", "target": "桃音"})
    ve = _last(w)
    assert ve.type == "hide" and s == "旅行者 替 桃音"
    # wait
    s = w.execute_action(t, {"action": "wait"})
    ve = _last(w)
    assert ve.type == "wait" and s == "旅行者 观望"
    w.close()


def test_world_event_structured():
    w = _world()
    w.visual_events.clear()
    w.world_event("雷电将军颁布眼狩令: 全城神之眼一律收缴", now=7.0)
    ve = _last(w)
    assert ve.type == "world_event" and ve.actor == "世界"
    assert ve.description == "雷电将军颁布眼狩令: 全城神之眼一律收缴"
    assert ve.describe() == "世界事件: 雷电将军颁布眼狩令: 全城神之眼一律收缴"
    assert ve.to_dict()["description"].startswith("雷电将军")
    w.close()


def test_step_autonomous_resets_buffer_per_step():
    """step_autonomous 每步重置 visual_events, 不跨步累积。"""
    w = _world()
    orig = w.decide_agent
    w.decide_agent = lambda agent, mem="": (
        {"action": "talk", "target": "刚郎", "utterance": "锻把武器"}
        if agent.name == "旅行者" else {"action": "wait"})
    events, _ = w.step_autonomous(now=14.0)
    n1 = len(w.visual_events)
    assert n1 >= 1 and any(ve.type == "conversation" for ve in w.visual_events)
    # 第2步: 缓冲被重置, 不含第1步事件
    w.decide_agent = orig
    w.step_autonomous(now=19.0)
    assert all(ve.type == "wait" for ve in w.visual_events), \
        "第2步应只有 wait, 不残留第1步的 conversation"
    w.close()
