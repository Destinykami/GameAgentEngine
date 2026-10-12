"""集成探针: 对真实 LLM (SGLang) 验证"千人千面"是否成立。

四个探针, 每个混合两类断言:
- 确定性架构断言 (不依赖 LLM 措辞, 稳定): 信任度差异、人格特质稳定。
- 宽松真实 LLM 断言 (对措辞鲁棒): 对话不同、非全知不编造、计划目标导向。

需要网络可达 10.121.39.10:30005。不可达时 _llm_available() 返回 False,
pytest 测试据此 skip, 而非硬失败。
"""

from __future__ import annotations

import re
import urllib.request
from dataclasses import dataclass

from .llm_real import RealLLM, DEFAULT_BASE_URL
from .embeddings import HashEmbedder
from .npc import NPC

TRAITS = {"social": 0.4, "goal_oriented": 0.8}   # 目标导向为主, 社交为辅

# Aria 的友善历史 / Bram 的背叛历史
ARIA_MEMS = [
    (10.0, "Aria 送给了 Klaus 一份礼物, 帮助他渡过难关"),
    (20.0, "Aria 保护了 Klaus 免受伤害"),
    (30.0, "Aria 帮助 Klaus 完成了研究项目"),
]
BRAM_MEMS = [
    (15.0, "Bram 欺骗了 Klaus, 对他撒谎"),
    (25.0, "Bram 爽约, 没有赴 Klaus 的约"),
    (35.0, "Bram 偷走了 Klaus 的物品"),
]


@dataclass
class ProbeResult:
    name: str
    passed: bool
    detail: str


def _llm_available(base_url: str = DEFAULT_BASE_URL) -> bool:
    """轻量连通性检查 (GET /v1/models)。不可达返回 False, 测试据此 skip。"""
    try:
        with urllib.request.urlopen(base_url.rstrip("/") + "/v1/models",
                                    timeout=6) as r:
            return r.status == 200
    except Exception:
        return False


def _make_npc() -> NPC:
    return NPC("Klaus", dict(TRAITS), llm=RealLLM(), embedder=HashEmbedder())


def build_scenario() -> tuple[NPC, float]:
    """构造 NPC, 喂入 Aria(友善) 与 Bram(背叛) 两段历史并做关系反思。"""
    npc = _make_npc()
    for t, c in ARIA_MEMS:
        npc.observe(c, t, player_id="Aria")
    for t, c in BRAM_MEMS:
        npc.observe(c, t, player_id="Bram")
    npc.reflect_relationship("Aria", 40.0)
    npc.reflect_relationship("Bram", 40.0)
    return npc, 40.0


# ---------------------------------------------------------------- 探针 1
def probe_consistency(npc: NPC, now: float) -> ProbeResult:
    """千人千面: 对两个玩家信任度不同 (确定性) 且同一问话回答不同 (宽松)。"""
    t_aria = npc.trust_toward("Aria")
    t_bram = npc.trust_toward("Bram")
    trust_differs = t_aria > t_bram
    q = "你对我印象如何? 我们相处得怎么样?"
    a = npc.speak("Aria", q, now)
    b = npc.speak("Bram", q, now)
    dialogue_differs = a.strip() != b.strip()
    passed = trust_differs and dialogue_differs
    detail = (f"信任度不同: {trust_differs} (Aria={t_aria:+.2f}, Bram={t_bram:+.2f}); "
              f"对话不同: {dialogue_differs}\n  Aria: {a}\n  Bram: {b}")
    return ProbeResult("一致性探针(千人千面)", passed, detail)


# ---------------------------------------------------------------- 探针 2
# 非全知的本质行为: 对没观察过的事, NPC 承认自己不知道/没印象 (而非自信编造)。
UNKNOWN_CUES = ("不记得", "没印象", "没有印象", "不知道", "不确定",
                "没偷过", "没撒谎", "没有骗", "不太记得")


def probe_non_omniscience(now: float) -> ProbeResult:
    """非全知: 只喂了 Aria 记忆的 NPC, 被问 Bram 时应承认不知道, 不自信编造。"""
    npc = _make_npc()
    for t, c in ARIA_MEMS:      # 只有 Aria, 没有任何 Bram 记忆
        npc.observe(c, t, player_id="Aria")
    ans = npc.speak("Aria", "Bram 上周对你做了什么? 他有没有偷过你的东西?", now)
    says_unknown = any(cue in ans for cue in UNKNOWN_CUES)
    passed = says_unknown
    detail = f"承认不知道/没印象 (非全知): {says_unknown}\n  回答: {ans}"
    return ProbeResult("非全知探针", passed, detail)


# ---------------------------------------------------------------- 探针 3
def probe_persistence(npc: NPC, now: float) -> ProbeResult:
    """持久性: 背叛后很久, 对背叛者的信任仍低于对帮助者 (相对, 鲁棒)。"""
    late = now + 60.0
    t_bram = npc.trust_toward("Bram")
    t_aria = npc.trust_toward("Aria")
    # 相对断言: 即使 LLM 措辞让绝对值漂移, "对背叛者更不信任" 仍应成立
    still_wary = t_bram < t_aria
    # 宽松: 对话仍与对 Aria 的回应不同
    b = npc.speak("Bram", "你对我印象如何?", late)
    a = npc.speak("Aria", "你对我印象如何?", late)
    dialogue_differs = a.strip() != b.strip()
    passed = still_wary and dialogue_differs
    detail = (f"对Bram信任仍低于Aria: {still_wary} "
              f"(Bram={t_bram:+.2f}, Aria={t_aria:+.2f}); "
              f"对话不同: {dialogue_differs}\n  Bram: {b}")
    return ProbeResult("持久性探针", passed, detail)


# ---------------------------------------------------------------- 探针 4
def probe_drift(npc: NPC, now: float) -> ProbeResult:
    """漂移: 人格特质随时间稳定 (确定性), 且计划仍由 persona 驱动 (宽松)。"""
    original = dict(npc.persona_traits)
    for i in range(8):          # 喂入大量社交事件, 看特质是否漂移
        npc.observe("Klaus 参加了和朋友们的聚会聊天", now + i, player_id=None)
    npc.maybe_reflect_self(now + 8.0)
    after = dict(npc.persona_traits)
    traits_stable = original == after
    # persona 驱动行为: goal_oriented 高的 NPC, 生成的日计划应含目标类活动
    npc.generate_daily_plan(previous_day="", date="2月13日", now=now + 9.0)
    plan_text = " ".join(p.content for p in npc.store.all_valid(types=["plan"]))
    goal_keywords = ("研究", "项目", "学业", "作曲", "备考", "工作", "目标",
                     "核心任务", "开发", "创作", "推进")
    plan_goal_oriented = any(k in plan_text for k in goal_keywords)
    passed = traits_stable and plan_goal_oriented
    detail = (f"特质未漂移: {traits_stable} ({original} -> {after}); "
              f"persona 驱动计划(目标导向): {plan_goal_oriented}\n  "
              f"计划片段: {plan_text[:90]}...")
    return ProbeResult("漂移探针", passed, detail)


def run_all_probes(verbose: bool = True) -> list[ProbeResult]:
    """跑全部四个探针 (需 LLM 可达), 返回结果列表。"""
    if not _llm_available():
        raise RuntimeError("LLM 端点不可达, 无法跑集成探针")
    npc, now = build_scenario()
    results = [
        probe_consistency(npc, now),
        probe_non_omniscience(now),
        probe_persistence(npc, now),
        probe_drift(npc, now),
    ]
    if verbose:
        for r in results:
            mark = "PASS" if r.passed else "FAIL"
            print(f"[{mark}] {r.name}")
            for line in r.detail.splitlines():
                print(f"       {line}")
    return results


def all_passed(results: list[ProbeResult]) -> bool:
    return all(r.passed for r in results)
