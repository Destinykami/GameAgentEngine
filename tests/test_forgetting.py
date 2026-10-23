"""遗忘测试 (无网络, stub LLM): 部分衰减降权, 不删除。

遗忘现在是"降权"不是"抹除": 久未访问的记忆 importance 渐近降到
MIN_IMPORTANCE, 但 valid 恒为 1 (不失效)。被反思引用的观察受保护不降权,
被回忆过 (last_accessed) 的记忆衰减更慢。
"""

from __future__ import annotations


import pytest


from game_agent import NPC, MemoryRecord
from game_agent.memory.store import MIN_IMPORTANCE
from tests.test_persistence import _StubLLM, TRAITS


def _make(tmp_path) -> NPC:
    return NPC.create("Fade", dict(TRAITS), llm=_StubLLM(), data_dir=str(tmp_path))


def _by_id(npc, mem_type):
    return {m.id: m for m in npc.store.all_valid(types=[mem_type])}


def test_uncited_old_observation_downweighted_not_deleted(tmp_path):
    """未被反思引用的旧观察: 降权到 MIN_IMPORTANCE, 但保留 (不删除)。"""
    npc = _make(tmp_path)
    old = npc.observe("Fade 扫地", 0.0)                 # 世界观察, 无引用, importance 5.0
    npc.forget(now=720.0)                                # 30 天后
    obs = _by_id(npc, "observation")
    assert old in obs, "旧观察应保留 (降权不删除)"
    assert obs[old].importance == pytest.approx(MIN_IMPORTANCE), \
        "未引用的旧观察 importance 应降到下限"


def test_cited_observation_protected(tmp_path):
    """被有效反思引用为证据的观察受保护: importance 不降权, 保留。"""
    npc = _make(tmp_path)
    cited = npc.observe("Aria 帮 Fade 修了咖啡机", 0.0, player_id="Aria")
    npc.store.add(MemoryRecord(content="Aria 是值得信赖的伙伴",
                               timestamp=1.0, type="reflection",
                               player_id="Aria", evidence=[cited],
                               confidence=0.8))
    npc.forget(now=720.0)
    obs = _by_id(npc, "observation")
    assert cited in obs, "被反思引用的观察应保留"
    assert obs[cited].importance == pytest.approx(5.0), \
        "被引用的观察受保护, importance 不应降权"


def test_recent_memory_retains_importance(tmp_path):
    """近期记忆: 降权但远高于下限, 保留。"""
    npc = _make(tmp_path)
    fresh = npc.observe("Aria 今天送了一杯新豆子", 700.0, player_id="Aria")
    npc.forget(now=720.0)                                # 仅 20h 前
    obs = _by_id(npc, "observation")
    assert fresh in obs
    assert obs[fresh].importance > MIN_IMPORTANCE, "近期记忆不应被降到下限"
    assert obs[fresh].importance < 5.0, "近期记忆仍会被轻微降权"


def test_old_reflection_downweighted_not_deleted(tmp_path):
    """旧反思: 降权到 MIN_IMPORTANCE, 但保留 (不删除)。"""
    npc = _make(tmp_path)
    ref_id = npc.store.add(MemoryRecord(content="Aria 似乎喜欢咖啡",
                                        timestamp=0.0, type="reflection",
                                        player_id="Aria", evidence=[],
                                        confidence=0.5))
    npc.forget(now=1000.0)                               # ~41 天
    refs = _by_id(npc, "reflection")
    assert ref_id in refs, "旧反思应保留 (降权不删除)"
    assert refs[ref_id].importance == pytest.approx(MIN_IMPORTANCE)


def test_recalled_memory_decays_slower(tmp_path):
    """被回忆过 (last_accessed 刷新) 的记忆衰减更慢: 同一时刻, 被回忆的仍高于
    下限, 从未被回忆的已触底。"""
    npc = _make(tmp_path)
    recalled = npc.observe("Aria 帮 Fade 修了咖啡机", 0.0, player_id="Aria")
    never = npc.observe("Fade 擦桌子", 0.0)                # 对照: 从不被回忆
    npc.store.merge_observation(recalled, now=240.0)
    # merge 刷新 last_accessed=240, importance 5.0→6.0 (固定 +1 强化)
    npc.forget(now=300.0)
    obs = _by_id(npc, "observation")
    # 被回忆: age=60h, factor=0.5^1.25≈0.42, 6.0*0.42≈2.52 → 高于下限
    # 未回忆: age=300h, factor≈0.013, 5.0*0.013≈0.06 → 触底 1.5
    assert obs[recalled].importance > MIN_IMPORTANCE, "被回忆记忆衰减更慢, 仍高于下限"
    assert obs[never].importance == pytest.approx(MIN_IMPORTANCE), "未回忆记忆触底"


def test_trust_does_not_fade_with_forgetting(tmp_path):
    """信任度不随遗忘淡化: 帮助记忆被降权 (但不删除) 后, 信任保持不变。

    遗忘只降 importance 不删除, 且 judge_trust 只看内容不看 importance,
    所以久远的帮助/背叛仍是关系认知, 信任不因"久远"而清零。
    """
    npc = _make(tmp_path)
    npc.observe("Aria 帮 Fade 修了咖啡机", 0.0, player_id="Aria")
    trust_before = npc.trust_toward("Aria")
    assert trust_before > 0, "帮助应产生正信任"
    # 遗忘降权: 帮助记忆 importance 降到下限, 但保留 (不删除)
    down = npc.forget(now=720.0)
    assert down, "帮助记忆应被降权"
    obs = _by_id(npc, "observation")
    help_id = down[0]
    assert help_id in obs, "被降权的帮助记忆应保留 (不删除)"
    # 强制重判信任 (清签名缓存), 验证不淡化
    npc.decider.clear_cache()
    trust_after = npc.trust_toward("Aria")
    assert trust_after == pytest.approx(trust_before), \
        "信任度不应随遗忘 (降权) 淡化"


def test_auto_sweep_on_time_advance(tmp_path):
    """游戏时钟跨 SWEEP_INTERVAL 时, observe 自动触发遗忘清扫 (降权)。"""
    from game_agent.cognition.npc import SWEEP_INTERVAL
    npc = _make(tmp_path)
    old = npc.observe("Fade 擦桌子", 0.0)                # _last_sweep 设为 0
    # 第二次 observe 把时钟推到 200h 后: 跨越清扫间隔 → 自动清扫;
    # 旧观察 age=200h, factor=0.5^(200/48)≈0.035, 5.0*0.035≈0.18 → 降到下限
    npc.observe("Aria 来了", SWEEP_INTERVAL + 194.0, player_id="Aria")
    obs = _by_id(npc, "observation")
    assert old in obs, "自动清扫应降权而非删除"
    assert obs[old].importance == pytest.approx(MIN_IMPORTANCE)


def test_repeated_observation_merges_plus_one_not_double_count(tmp_path, monkeypatch):
    """重复观察走生产路径 (observe → 去重合并): 强化是固定 +1, 不是把新观察的
    完整 importance 再加一遍 (事件重要性首次入库时已计入, 再加 = 双重计分)。"""
    npc = _make(tmp_path)
    first = npc.observe("Aria 帮 Fade 修了咖啡机", 0.0, player_id="Aria")
    # 跳过 6h 自动遗忘清扫, 单独验证 merge 的强化 (否则 +1 前会先被降权)
    monkeypatch.setattr(npc, "forget", lambda now: [])
    second = npc.observe("Aria 帮 Fade 修了咖啡机", 7.0, player_id="Aria")
    assert second == first, "近义观察应合并进同一条记录"
    obs = _by_id(npc, "observation")
    assert len(obs) == 1, "合并不新增记录"
    assert obs[first].importance == pytest.approx(6.0), \
        "时间窗外重复 = +1 强化 (5.0→6.0), 不是加全量 importance (5.0→10.0)"
    assert obs[first].last_accessed == pytest.approx(7.0), "合并应刷新 last_accessed"


def test_merge_reinforcement_caps_at_ten(tmp_path):
    """合并强化有上限: 反复 merge 渐近到 10, 不无限增长。"""
    npc = _make(tmp_path)
    obs_id = npc.observe("Aria 帮 Fade 修了咖啡机", 0.0, player_id="Aria")
    for i in range(30):   # 5.0 + 30 → 远超上限, 应收敛到 10
        new = npc.store.merge_observation(obs_id, now=10.0 + i)
    assert new == pytest.approx(10.0), "importance 上限 10"


def _obs_store(importance: float = 8.0):
    from game_agent.memory.store import MemoryStore
    from game_agent.models.embeddings import HashEmbedder
    s = MemoryStore(HashEmbedder())
    s.add(MemoryRecord(content="测试观察", timestamp=0.0,
                       type="observation", importance=importance))
    return s


def test_decay_idempotent_not_compound(tmp_path):
    """E1: 衰减是幂等水位 (base * 0.5**(age/hl)), 不是对已衰减值再乘满年龄因子。
    单次 48h 衰减与每 6h 高频清扫到 48h 必须一致 —— 旧实现后者触底 (复合加速)。"""
    single = _obs_store(8.0)
    single.decay_and_forget(now=48.0)
    swept = _obs_store(8.0)
    for t in range(6, 49, 6):          # SWEEP_INTERVAL=6h 的生产节奏
        swept.decay_and_forget(now=float(t))
    assert single.all_valid()[0].importance == pytest.approx(4.0), \
        "单次半衰期: 8.0 * 0.5^(48/48) = 4.0"
    assert swept.all_valid()[0].importance == pytest.approx(4.0), \
        "高频清扫不得复合加速 (旧实现触底 1.5, 半衰期语义失效)"


def test_decay_rescan_no_drift(tmp_path):
    """E1: 同一时刻重扫不漂移 (幂等) —— 重算从基线出发, 结果与扫几次无关。"""
    s = _obs_store(8.0)
    s.decay_and_forget(now=30.0)
    v1 = s.all_valid()[0].importance
    s.decay_and_forget(now=30.0)        # 原样重扫
    v2 = s.all_valid()[0].importance
    assert v1 == pytest.approx(v2), "重扫不得漂移 (旧实现每次再乘一遍因子)"


def test_merge_raises_decay_baseline(tmp_path):
    """E1: merge 提升 importance 时同步抬高衰减基线 —— 衰减从提升后的值起,
    不把合并的 +1 增益抹掉。"""
    s = _obs_store(8.0)
    mid = s.all_valid()[0].id
    s.merge_observation(mid, now=6.0)   # 时间窗外 +1 → 9.0, 基线抬到 9.0
    rec = s.all_valid()[0]
    assert rec.importance == pytest.approx(9.0)
    assert rec.base_importance == pytest.approx(9.0), "基线应随 merge 抬高"
    s.decay_and_forget(now=30.0)        # 距 last_accessed(6) 24h: 9.0 * 0.5^0.5 ≈ 6.36
    got = s.all_valid()[0].importance
    assert got == pytest.approx(9.0 * (0.5 ** 0.5)), \
        f"应从基线 9.0 衰减 (得 6.36), 实际 {got:.4f} (抹掉增益会是 8.0*0.707=5.66)"


def test_merge_does_not_accumulate_reflection_trigger(tmp_path):
    """E7: merge 合并的重复是零新信息, 不累积到反思触发器 —— 反思由新信息驱动,
    不是旧信息的反复强化。世界层每步 perceive→observe→去重合并重放位置观察,
    若 merge 分支仍累加原始 importance (世界感知常 8-10), 零新信息几步就顶满
    反思阈值, 产出"1 条观察、6 步 6 条反思"的膨胀 (E6 48:9 表的生成机制)。
    新观察是新信息, 照常累积。"""
    npc = _make(tmp_path)
    # 同一条观察重放 6 次: 首次新入库 (+5), 后 5 次近义合并 (+0)
    for i in range(6):
        npc.observe("旅行者 出现在 治疗堂, 靠近 桃音", float(i))
    assert npc.runtime_state().importance_accum == pytest.approx(5.0), \
        f"重放 6 次只应累积首次新观察 (5.0), 实际 {npc.runtime_state().importance_accum} (旧实现=30.0)"
    assert len(npc.store.all_valid(types=["observation"])) == 1, "近义观察应合并成 1 条"
    # 一条全新观察 = 新信息, 照常累积 +5
    npc.observe("执行官 在 市场 收缴神之眼", 10.0)
    assert npc.runtime_state().importance_accum == pytest.approx(10.0), "新观察照常累积"
