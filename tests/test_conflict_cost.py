"""冲突检测成本封顶测试 (M2 回归)。

- 每个反思只查最近 CONFLICT_RECENT_OBS 条更晚观察: 15 条更晚矛盾观察只触发
  K 次 judge_conflict, 不再 O(反思×观察) 全量配对。
- 置信度跌破 CONFLICT_DECAY_FLOOR 的反思直接跳过: 0 次调用, 置信度不动。
- 窗口内强矛盾仍失效 (失效路径不受 K 封顶影响)。
- 窗口外的旧矛盾不再回查 —— 它该在还是新证据时被处理, 这是 K 封顶的有意取舍。
无网络, 计数 stub LLM。
"""

from __future__ import annotations


import pytest


from game_agent import MemoryRecord, MemoryStore
from game_agent.models.embeddings import HashEmbedder
from game_agent.cognition.reflection import ReflectionEngine, CONFLICT_RECENT_OBS
from tests.test_persistence import _StubLLM


class CountingConflictLLM(_StubLLM):
    """judge_conflict 计数, 强度按观察内容查表 (查不到用默认)。"""

    def __init__(self, severities: dict[str, int] | None = None,
                 default: int = 0) -> None:
        super().__init__()
        self.calls = 0
        self._severities = severities or {}
        self._default = default

    def judge_conflict(self, reflection, observation):
        self.calls += 1
        return self._severities.get(observation, self._default)


def _store(ref_conf: float, observations: list[tuple[float, str]]) -> MemoryStore:
    store = MemoryStore(HashEmbedder())
    for ts, content in observations:
        store.add(MemoryRecord(content=content, timestamp=ts,
                               type="observation", player_id="Aria",
                               importance=6.0))
    store.add(MemoryRecord(content="Aria 是值得信赖的伙伴", timestamp=0.0,
                           type="reflection", player_id="Aria", evidence=[],
                           confidence=ref_conf, base_confidence=ref_conf))
    return store


def test_conflict_check_bounded_to_recent_k():
    """15 条更晚的部分矛盾观察, 只触发 K 次 judge_conflict (不是 15 次)。"""
    obs = [(float(i), f"Aria 第{i}次爽约") for i in range(1, 16)]   # t=1..15
    store = _store(0.8, obs)
    llm = CountingConflictLLM(default=5)   # 全部部分矛盾 (decay 带)
    ReflectionEngine(llm, HashEmbedder()).check_conflicts(store, "Aria", now=20.0)
    assert llm.calls == CONFLICT_RECENT_OBS, \
        f"只应查最近 {CONFLICT_RECENT_OBS} 条, 实际 {llm.calls} 次"
    ref = store.all_valid(player_id="Aria", types=["reflection"])[0]
    # decay_count 被 K 封顶 → 置信度最低到 base * 0.5^K, 不再被 15 条磨到零
    assert ref.confidence == pytest.approx(0.8 * (0.5 ** CONFLICT_RECENT_OBS))


def test_low_confidence_reflection_skipped():
    """置信度跌破地板的反思: 0 次调用, 置信度原样不动。"""
    obs = [(1.0, "Aria 又一次放鸽子"), (2.0, "Aria 说话不算数")]
    store = _store(0.05, obs)   # 0.05 < 0.1 地板
    llm = CountingConflictLLM(default=5)
    ReflectionEngine(llm, HashEmbedder()).check_conflicts(store, "Aria", now=3.0)
    assert llm.calls == 0, "已死信念不应再花 LLM 调用"
    ref = store.all_valid(player_id="Aria", types=["reflection"])[0]
    assert ref.confidence == pytest.approx(0.05), "跳过的反思置信度不动"


def test_strong_conflict_in_window_invalidates():
    """窗口内的强矛盾 (severity>=7) 仍直接失效 —— 失效路径不受 K 封顶影响。"""
    obs = [(1.0, "Aria 今天来了"), (2.0, "Aria 背叛了 Klaus")]
    store = _store(0.8, obs)
    llm = CountingConflictLLM(severities={"Aria 背叛了 Klaus": 8})
    ReflectionEngine(llm, HashEmbedder()).check_conflicts(store, "Aria", now=3.0)
    assert store.all_valid(player_id="Aria", types=["reflection"]) == [], \
        "窗口内强矛盾应失效反思"
    assert any(r.id is not None for r in store.all_invalid())


def test_old_conflict_out_of_window_not_recalled():
    """窗口外的旧矛盾不再回查 (K 封顶的有意取舍): 1 条旧强矛盾被 12 条新中性
    观察挤出窗口后, 反思不再被它失效。它该在还是新证据时被处理。"""
    obs = [(1.0, "Aria 背叛了 Klaus")]                      # 旧强矛盾 t=1
    obs += [(float(i), f"Aria 第{i}次正常来往") for i in range(2, 14)]   # t=2..13 中性
    store = _store(0.8, obs)
    llm = CountingConflictLLM(severities={"Aria 背叛了 Klaus": 8})   # 默认 0
    ReflectionEngine(llm, HashEmbedder()).check_conflicts(store, "Aria", now=20.0)
    # 窗口 = 最近 K 条 = t=4..13 的中性观察, 不含 t=1 的旧强矛盾
    assert llm.calls == CONFLICT_RECENT_OBS
    refs = store.all_valid(player_id="Aria", types=["reflection"])
    assert len(refs) == 1 and refs[0].confidence == pytest.approx(0.8), \
        "窗口外的旧矛盾不回查, 反思保持原样 (有意取舍)"
