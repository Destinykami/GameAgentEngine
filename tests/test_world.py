"""世界层测试 (无网络, 阶段 0 骨架): 区域、实体、移动、时钟、距离、持久化往返。"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from persona_agent.world import World, Location, Entity, Player, distance
from tests.test_persistence import _StubLLM


def _inazuma_locations() -> list[Location]:
    """稻妻城 5 区域 (阶段 0 骨架, NPC 尚未接入)。"""
    return [Location("主城街道", 0, 0),
            Location("治疗堂", 1, 0),
            Location("锻造坊", 2, 0),
            Location("眼狩署", 0, 1),
            Location("神樱庭", 0, 3)]


def _world(tmp_path, persistent: bool = True) -> World:
    path = os.path.join(str(tmp_path), "world.db") if persistent else None
    return World("稻妻城", _inazuma_locations(), path=path)


def test_move_and_clock(tmp_path):
    w = _world(tmp_path)
    w.add_entity(Player("旅行者", w.locations["主城街道"]))
    w.move("旅行者", "治疗堂", now=10.0)
    assert w.get("旅行者").location.name == "治疗堂"
    assert w.clock == 10.0
    w.close()


def test_clock_monotonic(tmp_path):
    """时钟取 max, 乱序事件不回退。"""
    w = _world(tmp_path)
    w.advance(20.0)
    w.advance(5.0)          # 乱序的更早事件
    assert w.clock == 20.0
    w.close()


def test_distance(tmp_path):
    w = _world(tmp_path)
    a = Player("旅行者", w.locations["主城街道"])
    b = Entity("npc", "桃音", w.locations["神樱庭"])
    c = Entity("npc", "刚郎", w.locations["主城街道"])
    assert distance(a, b) == pytest.approx(3.0)   # (0,0)→(0,3)
    assert distance(a, c) == pytest.approx(0.0)   # 同区域
    w.close()


def test_save_load_roundtrip(tmp_path):
    """保存/加载往返: 实体位置 + 时钟恢复一致。"""
    w = _world(tmp_path)
    w.add_entity(Player("旅行者", w.locations["主城街道"]))
    w.add_entity(Entity("npc", "桃音", w.locations["治疗堂"]))
    w.move("旅行者", "锻造坊", now=15.0)
    w.save()
    w.close()

    w2 = _world(tmp_path)          # 同 path, 重新打开
    w2.load()
    assert w2.get("旅行者").location.name == "锻造坊"
    assert w2.get("桃音").location.name == "治疗堂"
    assert w2.clock == pytest.approx(15.0)
    w2.close()


def test_inmemory_cannot_persist(tmp_path):
    w = _world(tmp_path, persistent=False)
    with pytest.raises(RuntimeError):
        w.save()


# ---------------------------------------------------------------- 阶段 1: 多 NPC 注册 + 玩家共存
def test_multi_npc_registration(tmp_path):
    """世界可注册多个 NPC + 一个玩家, 各自独立实体与认知对象。"""
    w = _world(tmp_path)
    w.add_npc("桃音", {"social": 0.8, "goal_oriented": 0.3},
              llm=_StubLLM(), data_dir=str(tmp_path), location="治疗堂")
    w.add_npc("刚郎", {"social": 0.3, "goal_oriented": 0.8},
              llm=_StubLLM(), data_dir=str(tmp_path), location="锻造坊")
    w.add_player("旅行者", "主城街道")
    assert w.npc("桃音") is not None and w.npc("刚郎") is not None
    assert w.get("旅行者").kind == "player"
    assert w.get("桃音").location.name == "治疗堂"
    assert w.get("刚郎").location.name == "锻造坊"
    w.close()


def test_multi_npc_trust_isolation(tmp_path):
    """同一玩家对两个 NPC 的信任流独立: 帮桃音、骗刚郎, 互不污染。"""
    w = _world(tmp_path)
    w.add_npc("桃音", {"social": 0.8, "goal_oriented": 0.3},
              llm=_StubLLM(), data_dir=str(tmp_path), location="治疗堂")
    w.add_npc("刚郎", {"social": 0.3, "goal_oriented": 0.8},
              llm=_StubLLM(), data_dir=str(tmp_path), location="锻造坊")
    w.add_player("旅行者", "主城街道")
    w.npc("桃音").observe("旅行者 帮 桃音 搬了货", 0.0, player_id="旅行者")
    w.npc("刚郎").observe("旅行者 骗了 刚郎 并 偷 走了他的豆子", 0.0, player_id="旅行者")
    assert w.npc("桃音").trust_toward("旅行者") > 0, "帮过的 NPC 信任应为正"
    assert w.npc("刚郎").trust_toward("旅行者") < 0, "骗过的 NPC 信任应为负"
    # 跨 NPC 记忆隔离: 桃音的记忆流不含刚郎的交互
    momone_mems = [m.content for m in w.npc("桃音").store.all_valid(player_id="旅行者")]
    assert not any("刚郎" in c for c in momone_mems), "跨 NPC 记忆不应污染"
    w.close()


def test_flush_social_clears_on_exception(tmp_path):
    """R4: reflect_relationship 抛异常 (LLM/DB 失败) 时 _step_social 仍清空 ——
    下步不重复处理旧社交事件 (重复反思 + 重复 LLM 调用)。单次失败不阻塞其余。"""
    llm = _StubLLM()
    w = _world(tmp_path)
    traits = {"social": 0.8, "goal_oriented": 0.3}
    w.add_npc("桃音", traits, llm=llm, data_dir=str(tmp_path), location="治疗堂")
    w._agent_llms["桃音"] = llm
    w._agent_personas["桃音"] = traits
    w.add_agent_player("旅行者", "治疗堂", "x", llm=llm)
    calls = {"n": 0}

    def boom(player_id, now):
        calls["n"] += 1
        raise RuntimeError("LLM 挂了")

    w.npc("桃音").reflect_relationship = boom
    w.execute_action(w.get("旅行者"), {"action": "help", "target": "桃音"})
    assert w._step_social, "社交动作应登记"
    w.flush_social(w.clock)          # 抛异常被内层 catch
    assert w._step_social == [], "异常后 _step_social 仍应清空 (R4)"
    assert calls["n"] == 1, "只调一次 reflect, 不因异常重复"
    # 重新登记 + 再 flush: 恰好再调一次, 不是重复旧事件
    w.execute_action(w.get("旅行者"), {"action": "help", "target": "桃音"})
    w.flush_social(w.clock)
    assert calls["n"] == 2, "再登记再 flush 恰好 +1 次, 不重复处理旧事件"
    w.close()


def test_flush_social_explicit_without_step(tmp_path):
    """R5: 只调 execute_action 不推进自治步, 显式 flush_social 也触发关系反思
    (契约明确, 不靠'之后恰好调 step_autonomous'才反思)。"""
    llm = _StubLLM()
    w = _world(tmp_path)
    w.add_npc("桃音", {"social": 0.8, "goal_oriented": 0.3},
              llm=llm, data_dir=str(tmp_path), location="治疗堂")
    w._agent_llms["桃音"] = llm
    w._agent_personas["桃音"] = {"social": 0.8, "goal_oriented": 0.3}
    w.add_agent_player("旅行者", "治疗堂", "x", llm=llm)
    w.execute_action(w.get("旅行者"), {"action": "help", "target": "桃音"})
    assert w._step_social, "社交动作应登记"
    w.flush_social(w.clock)   # 显式 flush, 不走 step_autonomous
    refs = w.npc("桃音").store.all_valid(player_id="旅行者", types=["reflection"])
    assert len(refs) >= 1, "显式 flush 应触发关系反思 (不推进自治步也生效)"
    w.close()


def _cap_llm():
    """捕获 decide_action 收到的 perception, 供断言信任度是否进决策输入。"""
    class Cap(_StubLLM):
        def __init__(self):
            super().__init__()
            self.perceptions = []
        def decide_action(self, name, goal, traits, perception, history, state):
            self.perceptions.append(perception)
            return {"action": "wait", "reason": "cap"}
    return Cap()


def test_decide_agent_feeds_trust_to_decision(tmp_path):
    """R1: NPC 的自治决策显式接收对视距内对象的信任度 —— 帮过的玩家 +1.00,
    骗过的玩家 -1.00, 稳定区分可信/不可信 (不再靠 LLM 从记忆文本猜)。无关系记忆
    的对象不列 (陌生人 trust 0 无信息量)。"""
    llm = _cap_llm()
    w = _world(tmp_path)
    traits = {"social": 0.8, "goal_oriented": 0.3}
    w.add_npc("桃音", traits, llm=llm, data_dir=str(tmp_path), location="治疗堂")
    w._agent_llms["桃音"] = llm
    w._agent_personas["桃音"] = traits
    # 正信任: 旅行者帮过桃音
    w.npc("桃音").observe("旅行者 帮 桃音 修了炉子", 0.0, player_id="旅行者")
    w.add_player("旅行者", "治疗堂")          # 同区域, 视距内
    w.decide_agent(w.get("桃音"))
    trust_seg = [s for s in llm.perceptions[0].split(" | ") if "信任度" in s]
    assert trust_seg and "旅行者 +1.00" in trust_seg[0], \
        f"正信任玩家应 +1.00 进决策 perception, 实际: {llm.perceptions[0]!r}"
    w.close()

    # 负信任: 另一世界里旅行者骗过桃音 → -1.00
    llm2 = _cap_llm()
    w2 = _world(tmp_path)
    w2.add_npc("刚郎", {"social": 0.3, "goal_oriented": 0.8},
               llm=llm2, data_dir=str(tmp_path), location="锻造坊")
    w2._agent_llms["刚郎"] = llm2
    w2._agent_personas["刚郎"] = {"social": 0.3, "goal_oriented": 0.8}
    w2.npc("刚郎").observe("旅行者 骗了 刚郎 并 偷 走了他的豆子", 0.0, player_id="旅行者")
    w2.add_player("旅行者", "锻造坊")
    w2.decide_agent(w2.get("刚郎"))
    trust_seg2 = [s for s in llm2.perceptions[0].split(" | ") if "信任度" in s]
    assert trust_seg2 and "旅行者 -1.00" in trust_seg2[0], \
        f"负信任玩家应 -1.00 进决策 perception, 实际: {llm2.perceptions[0]!r}"
    w2.close()


def test_execute_action_wires_npc_memory_and_reflection(tmp_path):
    """E16: 自治世界的社交动作 (talk/attack/help) 进目标 NPC 的记忆/信任/反思层,
    不再只写 Entity.history。talk 有回话 (真对话); attack/help 只观察 (NPC 的
    反应由其下一步 decide_agent 行动承担)。step_autonomous 消费 _step_social 跑
    关系反思, 步末清空。信任度随新观察惰性更新。"""
    w = _world(tmp_path)
    llm = _StubLLM()
    traits = {"social": 0.8, "goal_oriented": 0.3}
    w.add_npc("桃音", traits, llm=llm, data_dir=str(tmp_path), location="治疗堂")
    w._agent_llms["桃音"] = llm          # 让 decide_agent 能决策 (自治循环)
    w._agent_personas["桃音"] = traits
    w.add_agent_player("旅行者", "治疗堂", "帮助持眼者", llm=llm)   # 同区域 → full 档
    w.clock = 10.0

    # talk: 观察进记忆流 + 回话 (真对话)
    out = w.execute_action(w.get("旅行者"),
                           {"action": "talk", "target": "桃音", "utterance": "帮帮我"})
    assert "← 桃音" in out, "talk 应有 NPC 回话 (真对话)"
    obs = w.npc("桃音").store.all_valid(player_id="旅行者", types=["observation"])
    assert any("帮帮我" in o.content for o in obs), "talk 应进 NPC 关系观察"

    # attack: 观察进记忆流, 无回话 (NPC 不'回话'挨打, 反应由下一步行动承担)
    w.execute_action(w.get("旅行者"), {"action": "attack", "target": "桃音"})
    obs = w.npc("桃音").store.all_valid(player_id="旅行者", types=["observation"])
    assert any("攻击" in o.content for o in obs), "attack 应进 NPC 关系观察"

    # 社交动作登记进 _step_social; step_autonomous 消费它跑关系反思, 步末清空
    assert w._step_social, "社交动作应登记 _step_social 待反思"
    w.step_autonomous(now=10.5)
    refs = w.npc("桃音").store.all_valid(player_id="旅行者", types=["reflection"])
    assert len(refs) >= 1, "step_autonomous 应对社交对象跑关系反思"
    assert w._step_social == [], "步末 _step_social 应清空"
    w.close()


# ---------------------------------------------------------------- 阶段 2: 空间感知 → 观察
def _world_with_npc_player(tmp_path):
    w = _world(tmp_path)
    w.add_npc("桃音", {"social": 0.8, "goal_oriented": 0.3},
              llm=_StubLLM(), data_dir=str(tmp_path), location="治疗堂")
    return w


def test_perceive_nearby_player_generates_observation(tmp_path):
    """玩家走进 NPC 视距 → 感知生成观察; 离开视距 → 不生成。"""
    w = _world_with_npc_player(tmp_path)
    w.add_player("旅行者", "主城街道")          # 距治疗堂(1,0)=1.0 < 1.5 视距内
    ids = w.perceive("桃音", now=1.0)
    assert len(ids) >= 1, "视距内玩家应被感知"
    assert w.npc("桃音").memory_count(player_id="旅行者") >= 1
    w.move("旅行者", "神樱庭", now=2.0)          # 距治疗堂 sqrt(1+9)=3.16 > 1.5 视距外
    ids2 = w.perceive("桃音", now=2.0)
    assert ids2 == [], "玩家离开视距后不应再感知"
    w.close()


def test_perceive_idle_no_observation(tmp_path):
    """idle 档位的 NPC 不感知。"""
    w = _world_with_npc_player(tmp_path)
    w.add_player("旅行者", "治疗堂")             # 同区域 (距离 0)
    w.npc("桃音").set_tier("idle")
    assert w.perceive("桃音", now=1.0) == [], "idle 档位不应感知"
    w.close()


def test_perceive_dedup_no_flooding(tmp_path):
    """重复感知同一在场, 走观察去重合并, 不灌水。"""
    w = _world_with_npc_player(tmp_path)
    w.add_player("旅行者", "治疗堂")             # 同区域
    w.perceive("桃音", now=1.0)
    w.perceive("桃音", now=2.0)                  # 重复感知同一在场
    assert w.npc("桃音").memory_count(player_id="旅行者") == 1, \
        "重复感知同一在场应去重合并, 不灌水"
    w.close()


def test_perceive_full_vs_compressed_granularity(tmp_path):
    """full 档感知富细节, compressed 档感知稀疏。"""
    w = _world_with_npc_player(tmp_path)
    w.add_player("旅行者", "治疗堂")
    w.npc("桃音").set_tier("compressed")
    w.perceive("桃音", now=1.0)
    comp_content = w.npc("桃音").store.all_valid(player_id="旅行者")[0].content
    w.npc("桃音").store.invalidate(
        w.npc("桃音").store.all_valid(player_id="旅行者")[0].id)  # 清掉, 换档位再感知
    w.npc("桃音").set_tier("full")
    w.perceive("桃音", now=2.0)
    full_content = w.npc("桃音").store.all_valid(player_id="旅行者")[0].content
    assert "靠近" in full_content, "full 档应含富细节 (靠近)"
    assert "靠近" not in comp_content, "compressed 档应稀疏 (无'靠近')"
    w.close()


# ---------------------------------------------------------------- 阶段 3: 距离→档位自动调度 (清债)
def test_tier_of_distance(tmp_path):
    """距离调度: 同区域 full, 视距内 compressed, 远 idle。"""
    w = _world_with_npc_player(tmp_path)
    w.add_player("旅行者", "治疗堂")            # 同区域 (距离 0 <= 0.5) → full
    assert w.tier_of("桃音") == "full", "玩家同区域应 full"
    w.move("旅行者", "主城街道", now=1.0)       # 距治疗堂 1.0, 视距内 (<=1.5) → compressed
    assert w.tier_of("桃音") == "compressed", "玩家视距内应 compressed"
    w.move("旅行者", "神樱庭", now=2.0)         # 距治疗堂 3.16 > 1.5 → idle
    assert w.tier_of("桃音") == "idle", "玩家远离应 idle"
    w.close()


def test_schedule_tiers_idle_no_accumulation(tmp_path):
    """schedule_tiers 自动设档; idle 的 NPC 不累积重要性 (不触发反思)。"""
    w = _world_with_npc_player(tmp_path)
    w.add_player("旅行者", "神樱庭")            # 远离桃音 → idle
    tiers = w.schedule_tiers(now=1.0)
    assert tiers["桃音"] == "idle"
    assert w.npc("桃音")._tier == "idle"
    # idle 时 observe 仍记录记忆, 但不累积重要性 → 不触发反思
    w.npc("桃音").observe("旅行者 在远处忙别的", 1.0, player_id="旅行者")
    assert w.npc("桃音")._importance_accum == 0.0, "idle 不累积重要性"
    assert w.npc("桃音").memory_count(player_id="旅行者") == 1, "idle 仍记录记忆"
    w.close()


def test_tier_switch_affects_perception(tmp_path):
    """档位切换影响感知: 玩家走近升 full 感知富细节, 走远降 idle 不感知。"""
    w = _world_with_npc_player(tmp_path)
    w.add_player("旅行者", "治疗堂")            # 同区域 → full
    w.schedule_tiers(now=1.0)
    assert w.npc("桃音")._tier == "full"
    w.perceive("桃音", now=1.0)
    assert "靠近" in w.npc("桃音").store.all_valid(player_id="旅行者")[0].content
    w.move("旅行者", "神樱庭", now=2.0)         # 远离 → idle
    w.schedule_tiers(now=2.0)
    assert w.npc("桃音")._tier == "idle"
    assert w.perceive("桃音", now=2.0) == [], "idle 不感知"
    w.close()


# ---------------------------------------------------------------- 阶段 4: 世界事件
def test_world_event_radius_isolation(tmp_path):
    """世界事件只影响半径内 NPC, 范围外不受影响。"""
    w = _world(tmp_path)
    w.add_npc("桃音", {"social": 0.8, "goal_oriented": 0.3},
              llm=_StubLLM(), data_dir=str(tmp_path), location="治疗堂")     # (1,0)
    w.add_npc("雷电将军", {"social": 0.1, "goal_oriented": 0.9},
              llm=_StubLLM(), data_dir=str(tmp_path), location="神樱庭")     # (0,3)
    result = w.world_event("治疗堂着火了", now=5.0, at="治疗堂", radius=1.0)
    assert "桃音" in result, "桃音在火灾半径内应感知"
    assert "雷电将军" not in result, "将军在火灾半径外不应感知"
    assert w.npc("桃音").memory_count() >= 1, "桃音应记录火灾 (世界观察)"
    assert w.npc("雷电将军").memory_count() == 0, "将军不应记录范围外事件"
    w.close()


def test_world_event_global(tmp_path):
    """at=None 全图事件, 影响所有 NPC。"""
    w = _world(tmp_path)
    w.add_npc("桃音", {"social": 0.8, "goal_oriented": 0.3},
              llm=_StubLLM(), data_dir=str(tmp_path), location="治疗堂")
    w.add_npc("刚郎", {"social": 0.3, "goal_oriented": 0.8},
              llm=_StubLLM(), data_dir=str(tmp_path), location="锻造坊")
    result = w.world_event("眼狩令全城生效, 持神之眼者将被搜捕", now=5.0)
    assert set(result) == {"桃音", "刚郎"}, "全图事件应影响所有 NPC"
    w.close()


def test_world_event_skips_dead_npc(tmp_path):
    """L7: 死去的 NPC 不感知世界事件 (同 step/日计划的死亡检查)。"""
    w = _world(tmp_path)
    w.add_npc("桃音", {"social": 0.8, "goal_oriented": 0.3},
              llm=_StubLLM(), data_dir=str(tmp_path), location="治疗堂")
    w.add_npc("刚郎", {"social": 0.3, "goal_oriented": 0.8},
              llm=_StubLLM(), data_dir=str(tmp_path), location="锻造坊")
    w.get("刚郎").health = 0
    w.get("刚郎").dead = True
    result = w.world_event("眼狩令全城生效, 持神之眼者将被搜捕", now=5.0)
    assert set(result) == {"桃音"}, "死者不应感知世界事件"
    assert w.npc("刚郎").memory_count() == 0, "死者记忆流不应新增事件观察"
    w.close()


# ---------------------------------------------------------------- 阶段 5: 模拟驱动 + 端到端持久化
def test_step_loop(tmp_path):
    """step 循环: 时钟推进、距离调度切档、感知生成观察、自动持久化。"""
    w = _world(tmp_path)
    w.add_npc("桃音", {"social": 0.8, "goal_oriented": 0.3},
              llm=_StubLLM(), data_dir=str(tmp_path), location="治疗堂")
    w.add_player("旅行者", "治疗堂")            # 同区域 → full
    summary = w.step(now=10.0)
    assert summary["clock"] == 10.0
    assert summary["tiers"]["桃音"] == "full", "玩家同区域 → full"
    assert summary["new_observations"].get("桃音", 0) >= 1, "感知应生成观察"
    assert w.npc("桃音").memory_count(player_id="旅行者") >= 1
    w.close()


def test_world_end_to_end_persistence(tmp_path):
    """端到端持久化: 存世界(位置+时钟+NPC), 新世界加载后 NPC 记忆与面全恢复。"""
    w = _world(tmp_path)
    w.add_npc("桃音", {"social": 0.8, "goal_oriented": 0.3},
              llm=_StubLLM(), data_dir=str(tmp_path), location="治疗堂")
    w.add_player("旅行者", "主城街道")
    w.npc("桃音").observe("旅行者 帮 桃音 搬了货", 0.0, player_id="旅行者")
    trust_before = w.npc("桃音").trust_toward("旅行者")
    assert trust_before > 0
    w.move("旅行者", "锻造坊", now=15.0)
    w.save()
    w.close()

    # 新世界 (同 path) 加载, 传 llm/embedder 恢复 NPC
    w2 = _world(tmp_path)
    w2.load(llm=_StubLLM(), embedder=None)
    # 世界状态恢复: 位置 + 时钟
    assert w2.get("旅行者").location.name == "锻造坊"
    assert w2.clock == pytest.approx(15.0)
    # NPC 恢复: 记忆流 + 面 (信任) 全恢复
    assert w2.npc("桃音") is not None, "NPC 应随世界恢复"
    assert w2.npc("桃音").trust_toward("旅行者") == pytest.approx(trust_before), \
        "NPC 的信任 (面) 应恢复"
    assert w2.npc("桃音").memory_count(player_id="旅行者") >= 1, "NPC 记忆流应恢复"
    w2.close()
