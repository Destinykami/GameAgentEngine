"""共享流语义测试 (E2/E8 回归)。

E2: `player_id=None` 是"不过滤" (全玩家+共享流), `shared=True` 是"只取共享流"
(player_id IS NULL, 世界/自我记忆)。二者拆分后, 自我反思只吃共享流 (我是谁),
不再吞某玩家的关系观察 (谁对我做了什么) —— 那是关系反思的料, 混进来违反
"自我/面解耦"。relationship_trust(None) 是"无玩家" (世界事件), 返回中性 0.0,
不再把全玩家关系记忆合判出一个伪信任度。无网络。
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from persona_agent import MemoryRecord
from persona_agent.embeddings import HashEmbedder
from persona_agent.memory import MemoryStore
from persona_agent.reacting import ReactionDecider
from persona_agent.reflection import ReflectionEngine
from tests.test_persistence import _StubLLM


def _store_with_both() -> MemoryStore:
    s = MemoryStore(HashEmbedder())
    s.add(MemoryRecord(content="Klaus 把咖啡豆撒了一地", timestamp=0.0,
                       type="observation", importance=5.0, player_id=None))   # 共享流
    s.add(MemoryRecord(content="Aria 帮 Klaus 修了咖啡机", timestamp=1.0,
                       type="observation", importance=8.0, player_id="Aria"))  # 关系流
    return s


def test_all_valid_none_vs_shared():
    """all_valid(None)=全玩家+共享流; all_valid(shared=True)=只 NULL 流。"""
    s = _store_with_both()
    assert len(s.all_valid()) == 2, "None 是不过滤, 返回全部"
    shared = s.all_valid(shared=True)
    assert len(shared) == 1, "shared=True 只返回共享流"
    assert shared[0].player_id is None
    assert shared[0].content == "Klaus 把咖啡豆撒了一地"


def test_reflect_self_only_uses_shared_observations():
    """E8: 自我反思只基于共享流观察, 不吃 Aria 的关系观察。"""
    s = _store_with_both()
    ReflectionEngine(_StubLLM(), HashEmbedder()).reflect_self(s, now=2.0)
    refs = s.all_valid(shared=True, types=["reflection"])
    assert len(refs) == 1, "应产出一条自我反思"
    # 证据必须指向共享观察 (id 1), 不能是 Aria 的关系观察 (id 2)
    assert refs[0].evidence == [1], \
        f"自我反思证据应是共享观察, 实际 {refs[0].evidence} (吞了关系观察)"


def test_relationship_trust_none_is_neutral():
    """E2: trust(None) 是'无玩家' (世界事件), 返回 0.0, 不合判全玩家记忆。"""
    s = _store_with_both()
    s.add(MemoryRecord(content="Bram 骗 Klaus 咖啡豆", timestamp=2.0,
                       type="observation", importance=8.0, player_id="Bram"))
    dec = ReactionDecider(s, _StubLLM())
    assert dec.relationship_trust(None) == 0.0, "world 事件无关系, 信任度中性 0"


def test_relationship_trust_isolated_per_player():
    """各玩家信任度独立: Aria 与 Bram 各走各的记忆, 不串扰。"""
    s = _store_with_both()
    s.add(MemoryRecord(content="Bram 骗 Klaus 咖啡豆", timestamp=2.0,
                       type="observation", importance=8.0, player_id="Bram"))
    dec = ReactionDecider(s, _StubLLM())
    # _StubLLM.judge_trust 按内容判: 帮助→+1, 背叛→-1 (见 test_persistence)
    assert dec.relationship_trust("Aria") == pytest.approx(1.0)
    assert dec.relationship_trust("Bram") == pytest.approx(-1.0)
    assert dec.relationship_trust("Isabella") == 0.0, "无记忆的玩家 = 中性 0"
