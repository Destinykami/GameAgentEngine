"""成本闸门回归 (F2-3 / F2-4)。

- `world_event` 对同一事件文本只打一次重要性分, 所有 NPC 复用。
- `judge_trust` 输入封顶在 30 条: 高阶认知优先, 近期观察填满; 关系流再长
  也不会让 prompt 线性膨胀。
"""

from __future__ import annotations



from game_agent import Location, MemoryRecord, NPC, World
from game_agent.models.embeddings import HashEmbedder
from tests.test_persistence import _StubLLM, TRAITS


class _CountingLLM(_StubLLM):
    def __init__(self) -> None:
        super().__init__()
        self.importance_calls = 0
        self.trust_sizes = []
        self.trust_memories = []

    def score_importance(self, text, player_id=None):
        self.importance_calls += 1
        return super().score_importance(text, player_id)

    def judge_trust(self, memories, player_id):
        self.trust_sizes.append(len(memories))
        self.trust_memories.append(list(memories))
        return 0.0


def test_world_event_scores_importance_once(tmp_path):
    w = World("w", [Location("L", 0, 0)])
    llms = {}
    for name in ("A", "B", "C"):
        llm = _CountingLLM()
        llms[name] = llm
        w.add_npc(name, dict(TRAITS), llm=llm,
                  data_dir=str(tmp_path / name), location="L")
    w.world_event("眼狩令颁布", 1.0)
    assert sum(llm.importance_calls for llm in llms.values()) == 1, \
        "同一世界事件只应打一次分"
    assert all(w.npc(n).store.all_valid(shared=True, types=["observation"])
               for n in ("A", "B", "C")), "所有 NPC 仍应记录事件"
    w.close()


def test_observe_accepts_precomputed_importance():
    llm = _CountingLLM()
    npc = NPC("T", dict(TRAITS), llm=llm, embedder=HashEmbedder())
    npc.observe("预打分事件", 1.0, importance=7.0)
    assert llm.importance_calls == 0
    assert npc.store.all_valid()[0].importance == 7.0


def test_trust_input_is_capped_and_prioritizes_cognition():
    llm = _CountingLLM()
    npc = NPC("T", dict(TRAITS), llm=llm, embedder=HashEmbedder())
    for i in range(120):
        npc.observe(f"relation event unique{i} alpha{i}", float(i),
                    player_id="P")
    npc.trust_toward("P")
    assert llm.trust_sizes[-1] <= 30, \
        f"trust prompt 不应超过 30 条, 实际 {llm.trust_sizes[-1]}"
    captured = llm.trust_sizes[-1]
    assert captured >= 1

    # 高阶认知优先保留: 加入 5 条反思后重判, 反思仍应进入窗口
    for i in range(5):
        npc.store.add(MemoryRecord(content=f"reflection unique{i} beta{i}",
                                   timestamp=200.0 + i, type="reflection",
                                   player_id="P", confidence=0.8))
    npc.trust_toward("P")
    assert llm.trust_sizes[-1] <= 30
    mems = llm.trust_memories[-1]
    contents = [c for _t, c, _conf in mems]
    assert any("relation event unique119 alpha119" in c for c in contents),         "最新观察应在信任窗口内"
    assert sum(1 for t, _c, _conf in mems if t == "reflection") == 5,         "高阶认知应优先进入信任窗口"
