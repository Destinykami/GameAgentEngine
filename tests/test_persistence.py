"""持久化往返测试 (无网络, 用 stub LLM): create → observe → save → load → 断言。"""

from __future__ import annotations

import os

import pytest


from game_agent import NPC, MemoryStore
from game_agent.models.llm import LLMClient, LLMContext


class _StubLLM(LLMClient):
    """最小 stub: 返回固定值, 不联网, 仅用于持久化逻辑测试。"""

    def complete(self, ctx: LLMContext) -> str:
        return "stub-reply"

    def score_importance(self, text: str, player_id: str | None = None) -> float:
        return 5.0

    def reflection_questions(self, recent) -> list[str]:
        return ["stub-q"]

    def reflection_insights(self, evidence, n: int = 5):
        return [("stub-insight", [e[0] for e in evidence[:1]])] if evidence else []

    def generate_plan(self, persona_traits, previous_day, date, context=""):
        # context 是 NPC 近期记忆/世界事件 (世界背景驱动计划), stub 忽略
        return [(7, 9, "stub-activity")]

    def decompose_activity(self, activity, start, end):
        return [(start, end, "stub-subtask")]

    def score_event(self, event, persona_traits, current_plan=""):
        # 固定价值: 社交事件偏高, 供反应决策测试 (不联网)
        return (8.0, 1.0, 3.0)

    def judge_conflict(self, reflection, observation):
        # 离线确定性: 默认无矛盾 (不失效/不衰减任何反思), 离线架构测试不依赖冲突判定。
        return 0

    def judge_trust(self, memories, player_id):
        # 离线确定性: 用词表计数模拟 LLM 信任判断 (与旧生产语义一致),
        # 供离线架构测试断言信任值。真实 LLM 的信任质量由集成探针覆盖。
        # memories 是 (类型, 内容, 置信度); stub 只看内容, 置信度不参与词表计数
        # (真实 LLM 会按置信度少加权被削弱的反思)。
        from game_agent.cognition.reflection import TRUST_WORDS, DISTRUST_WORDS
        pos = sum(1 for _t, c, _conf in memories
                  if any(w in c for w in TRUST_WORDS + ("帮助", "帮", "感谢")))
        neg = sum(1 for _t, c, _conf in memories
                  if any(w in c for w in DISTRUST_WORDS + ("背叛", "欺骗", "撒谎", "骗", "偷")))
        total = pos + neg
        return (pos - neg) / total if total else 0.0

    def perceive_action(self, npc_name, player_name, action, context=""):
        # 离线确定性: 直接把动作拼成观察 (模拟 NPC 自己观察生成), 含"帮/骗"等
        # 词供 trust 词表断言。真实 LLM 的观察生成质量由集成验证覆盖。
        return f"{player_name} {action}"

    def decide_action(self, agent_name, goal, persona_traits, perception,
                      history, state):
        # 离线确定性: 默认等待 (不行动), 供多智能体循环骨架测试 (不联网)。
        # 真实 LLM 的决策质量由 world_auto_sim 集成验证覆盖。
        return {"action": "wait", "target": "", "utterance": "",
                "dest": "", "reason": "stub-wait"}

    def consolidate_observations(self, observations, player_id=None):
        # 离线确定性: 固定摘要 (条数可辨), 供固化逻辑测试 (不联网)。
        return f"stub-episode ({len(observations)} obs)"


TRAITS = {"social": 0.7, "goal_oriented": 0.5}


def test_create_save_load_roundtrip(tmp_path):
    npc = NPC.create("Testling", dict(TRAITS), llm=_StubLLM(),
                     data_dir=str(tmp_path))
    assert npc.store.is_persistent()
    assert os.path.exists(os.path.join(str(tmp_path), "Testling.db"))
    assert npc.memory_count() == 0

    # 喂入记忆 + 推进时钟
    npc.observe("Aria 帮 Testling 修好了咖啡机", 10.0, player_id="Aria")
    npc.observe("Testling 清理了桌子", 11.0)
    npc.save()
    count_before = npc.memory_count()
    assert count_before == 2

    # 加载: 元数据 + 记忆流 + 时钟全部恢复
    npc2 = NPC.load(os.path.join(str(tmp_path), "Testling.db"), llm=_StubLLM())
    assert npc2.name == "Testling"
    assert npc2.persona_traits == TRAITS
    assert npc2.memory_count() == count_before
    assert npc2.trust_toward("Aria") == npc.trust_toward("Aria")  # 信任状态随记忆恢复
    assert npc2.game_time == pytest.approx(11.0)  # 游戏时钟恢复

    # create 幂等: 对同名再 create 等价于 load
    npc3 = NPC.create("Testling", dict(TRAITS), llm=_StubLLM(),
                      data_dir=str(tmp_path))
    assert npc3.memory_count() == count_before


def test_memory_not_persistent_raises():
    npc = NPC("Ephemeral", dict(TRAITS), llm=_StubLLM())   # 默认 :memory:
    assert not npc.store.is_persistent()
    with pytest.raises(RuntimeError):
        npc.save()


def test_load_missing_meta_raises(tmp_path):
    # 裸 MemoryStore 文件没有 NPC 元数据
    from game_agent import HashEmbedder
    MemoryStore(HashEmbedder(), path=str(tmp_path / "bare.db")).close()
    with pytest.raises(ValueError):
        NPC.load(str(tmp_path / "bare.db"), llm=_StubLLM())
