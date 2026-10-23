"""社交层测试 (S1–S3, 无网络): NPC↔NPC 关系流泛化验证 + S2 社交在场感知。

S1/S3 的机制 (per-entity 关系观察 / 关系反思 / 信任) 已由 E16/flush_social/R1
实现, 本文件把它们的 NPC↔NPC 语义锁死成回归 (防止后续改动把"玩家专属"悄悄
改回去); S2 (在场感知) 是本次新增, 缺省关 = 现行为。
"""

from __future__ import annotations



from game_agent.world.runtime import World, Location, Entity, Player
from tests.test_persistence import _StubLLM

TRAITS = {"social": 0.7, "goal_oriented": 0.5}


def _locs() -> list[Location]:
    return [Location("主城街道", 0, 0),
            Location("眼狩署", 0, 1),
            Location("神樱庭", 0, 3)]


class _CountingLLM(_StubLLM):
    def __init__(self) -> None:
        super().__init__()
        self.importance_calls = 0

    def score_importance(self, text, player_id=None):
        self.importance_calls += 1
        return super().score_importance(text, player_id)


def _world(tmp_path, **kw) -> World:
    w = World("测试城", _locs(), path=None, **kw)
    return w


def _setup(w: World, tmp_path) -> None:
    """玩家与 A 同区域 (A=full), C 距玩家 1.0 (compressed), E 距玩家 3.0 (idle);
    B/D/F 分别与 A/C/E 同区域。"""
    w.add_player("玩家", "主城街道")
    w.add_npc("A", dict(TRAITS), llm=_StubLLM(), data_dir=str(tmp_path / "A"),
              location="主城街道")
    w.add_npc("B", dict(TRAITS), llm=_StubLLM(), data_dir=str(tmp_path / "B"),
              location="主城街道")
    w.add_npc("C", dict(TRAITS), llm=_StubLLM(), data_dir=str(tmp_path / "C"),
              location="眼狩署")
    w.add_npc("D", dict(TRAITS), llm=_StubLLM(), data_dir=str(tmp_path / "D"),
              location="眼狩署")
    w.add_npc("E", dict(TRAITS), llm=_CountingLLM(), data_dir=str(tmp_path / "E"),
              location="神樱庭")
    w.add_npc("F", dict(TRAITS), llm=_StubLLM(), data_dir=str(tmp_path / "F"),
              location="神樱庭")
    w.schedule_tiers(10.0)


# ---------------------------------------------------------------- S1/S3 既有机制锁死
def test_npc_to_npc_talk_observes_actor_stream(tmp_path):
    """S1: NPC A 对 NPC B 说话, B 的记忆流里出现 player_id=A 的关系观察
    (per-entity 流: player_id 字段承载任意 entity 名, 非玩家专属)。"""
    w = _world(tmp_path)
    _setup(w, tmp_path)
    w.execute_action(w.get("A"), {"action": "talk", "target": "B",
                                  "utterance": "今天天气不错"})
    obs = w.npc("B").store.all_valid(player_id="A", types=["observation"])
    # F1-1 后 talk 双向落库: B 既记得 A 说的话 (perceive_action), 也记得自己
    # 的回复 (speak 内部写入), 所以是 2 条而不是旧的 1 条。
    assert len(obs) == 2
    assert any("对TA说" in m.content for m in obs)
    assert any("我对 A 说: stub-reply" in m.content for m in obs)
    w.close()


def test_npc_to_npc_social_reflection(tmp_path):
    """S3: flush_social 对 NPC 行动者跑关系反思 —— B 对 A 形成关系反思
    (player_id=A 流, 与玩家面同机制)。"""
    w = _world(tmp_path)
    _setup(w, tmp_path)
    w.execute_action(w.get("A"), {"action": "talk", "target": "B",
                                  "utterance": "今天天气不错"})
    w.flush_social(10.5)
    refs = w.npc("B").store.all_valid(player_id="A", types=["reflection"])
    assert len(refs) >= 1
    # 自观察+回复回流后: A 的 B 面有两条 —— 自己说的 ("我对 B 说: 今天天气不错")
    # 和 B 的回复 ("B 说: stub-reply")。对话双向+自洽落记忆。
    a_about_b = w.npc("A").store.all_valid(player_id="B", types=["observation"])
    assert len(a_about_b) == 2
    contents = " | ".join(m.content for m in a_about_b)
    assert "我对 B 说" in contents and "stub-reply" in contents
    w.close()


def test_reply_flows_back_to_speaker(tmp_path):
    """回复回流: NPC A 问 NPC B, B 的回复 observe 进 A 的记忆流 (player_id=B),
    且出现在 A 下一步决策的记忆上下文里 —— 对话双向落记忆, 不再是一串独白。"""
    w = _world(tmp_path)
    _setup(w, tmp_path)
    w.execute_action(w.get("A"), {"action": "talk", "target": "B",
                                  "utterance": "你最近怎么样?"})
    # A 的 B 面有两条: 自己说的 (自观察回流) + B 的回复 (回复回流)
    a_about_b = w.npc("A").store.all_valid(player_id="B", types=["observation"])
    assert len(a_about_b) == 2
    contents = " | ".join(m.content for m in a_about_b)
    assert "你最近怎么样" in contents and "stub-reply" in contents
    # 说话者下一步决策的记忆上下文能看到回复 (all_valid()[-5:] 含最新观察)
    mems = [m.content for m in w.npc("A").store.all_valid()[-5:]]
    assert any("stub-reply" in m for m in mems)
    w.close()


def test_self_utterance_flows_back_to_speaker(tmp_path):
    """自观察回流: NPC A 说话时, 自己这句话 observe 进自己记忆流 (player_id=B,
    "我对 B 说: X") —— NPC 有了"我说过什么"的记忆, 不只记得对方说的。"""
    w = _world(tmp_path)
    _setup(w, tmp_path)
    w.execute_action(w.get("A"), {"action": "talk", "target": "B",
                                  "utterance": "帮我看看炉子"})
    a_about_b = w.npc("A").store.all_valid(player_id="B", types=["observation"])
    self_obs = [m for m in a_about_b if "我对 B 说" in m.content]
    assert len(self_obs) == 1
    assert "帮我看看炉子" in self_obs[0].content
    # 自观察与回复回流共存, 各一条
    reply_obs = [m for m in a_about_b if "stub-reply" in m.content]
    assert len(reply_obs) == 1
    w.close()


def test_no_self_utterance_for_player_speaker(tmp_path):
    """说话者是玩家时不自观察 (玩家无认知对象/记忆流), 目标 NPC 照常记得玩家的话。"""
    w = _world(tmp_path)
    _setup(w, tmp_path)
    w.execute_action(w.get("玩家"), {"action": "talk", "target": "B",
                                     "utterance": "你好"})
    # B 记得玩家说的 (既有 perceive_action, player_id=玩家)
    b_about_player = w.npc("B").store.all_valid(player_id="玩家", types=["observation"])
    assert any("你好" in m.content for m in b_about_player)
    w.close()


def test_reply_not_backflowed_for_player_speaker(tmp_path):
    """说话者是玩家时不回流 (玩家无认知对象/记忆流), 目标 NPC 照常回复。"""
    w = _world(tmp_path)
    _setup(w, tmp_path)
    w.execute_action(w.get("玩家"), {"action": "talk", "target": "B",
                                     "utterance": "你好"})
    # B 回复了 (回放事件带 reply), 但"回流"只针对 NPC 说话者, 玩家侧无记忆流可写
    conv = [ve for ve in w.visual_events if ve.type == "conversation"]
    assert conv and conv[-1].reply == "stub-reply"
    w.close()


# ---------------------------------------------------------------- S2 在场感知
def test_social_perception_default_off(tmp_path):
    """缺省关: 同区域的两个 NPC 互不产生观察 (现行为不变)。"""
    w = _world(tmp_path)
    _setup(w, tmp_path)
    w.perceive("A", 10.0)
    assert w.npc("A").store.all_valid(player_id="B", types=["observation"]) == []
    w.close()


def test_social_perception_full_tier_rich(tmp_path):
    """full 档: 新 NPC 进入视距产生富细节在场观察 (含'靠近'); 重复在场不重复
    入库 (过渡驱动); 离开再重现会再触发。"""
    w = _world(tmp_path, social_perception=True)
    _setup(w, tmp_path)
    w.perceive("A", 10.0)
    obs = w.npc("A").store.all_valid(player_id="B", types=["observation"])
    assert len(obs) == 1
    assert "靠近" in obs[0].content

    # 重复在场: 第二步不再产生新观察
    w.perceive("A", 11.0)
    assert len(w.npc("A").store.all_valid(player_id="B",
                                          types=["observation"])) == 1

    # B 离开视距 → 重现 → 再触发。重现内容与首次相同, 0.92 去重把它合并进原
    # 记录 (重复发生 = 被回忆: 刷新 last_accessed; importance 按 6h 时间窗限速,
    # 3h 内不 +1), 记录数不增。
    w.move("B", "神樱庭", now=12.0)
    w.schedule_tiers(12.0)
    w.perceive("A", 12.0)
    assert len(w.npc("A").store.all_valid(player_id="B",
                                          types=["observation"])) == 1
    w.move("B", "主城街道", now=13.0)
    w.schedule_tiers(13.0)
    w.perceive("A", 13.0)
    obs2 = w.npc("A").store.all_valid(player_id="B", types=["observation"])
    assert len(obs2) == 1
    assert obs2[0].last_accessed == 13.0   # 合并刷新了遗忘锚点
    assert obs2[0].importance == obs[0].importance         # 3h 内在限速窗内, 不 +1
    w.close()


def test_social_perception_compressed_tier_sparse(tmp_path):
    """compressed 档: 在场观察是稀疏版 (仅在场, 无'靠近')。"""
    w = _world(tmp_path, social_perception=True)
    _setup(w, tmp_path)
    w.perceive("C", 10.0)
    obs = w.npc("C").store.all_valid(player_id="D", types=["observation"])
    assert len(obs) == 1
    assert "靠近" not in obs[0].content
    w.close()


def test_social_perception_idle_tier_none(tmp_path):
    """idle 档: 不感知任何 NPC (零观察), 且零 LLM 调用 (成本闸门)。"""
    w = _world(tmp_path, social_perception=True)
    _setup(w, tmp_path)
    assert w.npc("E").tier == "idle"
    assert w.perceive("E", 10.0) == []
    assert w.npc("E").store.all_valid() == []
    assert w.npc("E").llm.importance_calls == 0   # type: ignore[attr-defined]
    w.close()


def test_social_perception_llm_cost(tmp_path):
    """成本口径: 每个在场**出现**一次 score_importance (observe 路径),
    重复在场零增量 (过渡驱动 + 去重兜底)。"""
    w = _world(tmp_path, social_perception=True)
    counting = _CountingLLM()
    w.add_player("玩家", "主城街道")
    w.add_npc("A", dict(TRAITS), llm=counting, data_dir=str(tmp_path / "A"),
              location="主城街道")
    w.add_npc("B", dict(TRAITS), llm=_StubLLM(), data_dir=str(tmp_path / "B"),
              location="主城街道")
    w.schedule_tiers(10.0)
    w.perceive("A", 10.0)
    assert counting.importance_calls == 2      # 玩家在场 + B 出现
    w.perceive("A", 11.0)
    assert counting.importance_calls == 2      # 重复在场先去重, 零 LLM 增量
    w.close()


def test_social_perception_reflection_via_flush(tmp_path):
    """在场观察进 _step_social → flush_social 对在场 NPC 跑关系反思
    (复用 E16 的 flush 路径: full 档且新观察才反思)。"""
    w = _world(tmp_path, social_perception=True)
    _setup(w, tmp_path)
    w.perceive("A", 10.0)
    w.flush_social(10.5)
    refs = w.npc("A").store.all_valid(player_id="B", types=["reflection"])
    assert len(refs) >= 1
    w.close()
