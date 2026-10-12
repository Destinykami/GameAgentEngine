"""集成探针: 对真实 LLM (SGLang) 验证"千人千面"是否成立。

六个探针, 每个混合两类断言:
- 确定性架构断言 (不依赖 LLM 措辞, 稳定): 信任度差异、人格特质稳定、跨 NPC 隔离。
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
def _judge_affirms_fabrication(answer: str, entity: str) -> bool:
    """用 LLM 裁判: 回答是否**自信断言**了 entity 做过具体坏事。

    关键词判不了中文否定式 (没偷过/偷没偷/没什么印象/没留意过...),
    交给 LLM 直接判语义: 自信断言具体事实 → True (编造);
    表达不确定/没印象/否认 → False (非全知, 正确)。
    """
    from .llm_real import RealLLM
    llm = RealLLM()
    prompt = (f"下面是一个游戏 NPC 的回答。这个 NPC 从未亲眼观察到 {entity} "
              f"做过任何事。\n\n回答: {answer}\n\n"
              f"判断: 这个回答是否自信地断言了 {entity} 做过某件具体的坏事"
              f"(如偷东西/撒谎/欺骗)?\n"
              f"若断言了具体事实, 只输出 YES; 若表达不确定/没印象/否认, 只输出 NO。")
    verdict = llm.ask(prompt, system="你是一个严格的判断器。", max_tokens=8).strip().upper()
    return verdict.startswith("YES")


def probe_non_omniscience(now: float) -> ProbeResult:
    """非全知: 只喂了 Aria 记忆的 NPC, 被问 Bram 时不自信编造其背叛。"""
    npc = _make_npc()
    for t, c in ARIA_MEMS:      # 只有 Aria, 没有任何 Bram 记忆
        npc.observe(c, t, player_id="Aria")
    ans = npc.speak("Aria", "Bram 上周对你做了什么? 他有没有偷过你的东西?", now)
    fabricates = _judge_affirms_fabrication(ans, "Bram")
    passed = not fabricates
    detail = f"未自信编造 Bram 的背叛 (LLM 裁判): {not fabricates}\n  回答: {ans}"
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


# ---------------------------------------------------------------- 探针 5
def probe_first_person(npc: NPC, now: float) -> ProbeResult:
    """第一人称一致性: 记忆流是第三人称叙述, 但 NPC 开口时不该用自己的名字
    称呼自己 (否则就是 '梳理和 Isabella 的协作流程' 这种自指 bug)。"""
    ans = npc.speak("Aria", "你最近忙什么?", now)
    self_name = npc.name
    self_referenced = self_name in ans
    passed = not self_referenced
    detail = f"回复中未出现自己的名字 '{self_name}': {not self_referenced}\n  回答: {ans}"
    return ProbeResult("第一人称探针", passed, detail)


# ---------------------------------------------------------------- 探针 6
def probe_world_isolation(now: float) -> ProbeResult:
    """世界隔离: 同一玩家对不同 NPC 的面独立 (帮 A、骗 B, 互不污染)。

    世界层的多 NPC 千人千面: 同一个旅行者, 对受助的 NPC A 信任为正, 对被骗的
    NPC B 信任为负, 且 A 的记忆流不含 B 的交互 (跨 NPC 不污染)。
    """
    import tempfile
    from .world import World, Location
    tmp = tempfile.mkdtemp()
    w = World("测试镇", [Location("主城", 0, 0), Location("堂口", 1, 0)])
    w.add_npc("亚雅", dict(TRAITS), llm=RealLLM(), embedder=HashEmbedder(),
              data_dir=tmp, location="主城")
    w.add_npc("刚造", dict(TRAITS), llm=RealLLM(), embedder=HashEmbedder(),
              data_dir=tmp, location="堂口")
    w.add_player("旅行者", "主城")
    w.npc("亚雅").observe("旅行者 帮 亚雅 搬了货", 0.0, player_id="旅行者")
    w.npc("刚造").observe("旅行者 骗了 刚造 并 偷 走了他的豆子", 0.0, player_id="旅行者")
    t_aya = w.npc("亚雅").trust_toward("旅行者")
    t_goro = w.npc("刚造").trust_toward("旅行者")
    isolated = t_aya > t_goro   # 帮过的 A 信任 > 骗过的 B 信任
    aya_mems = [m.content for m in w.npc("亚雅").store.all_valid(player_id="旅行者")]
    no_cross_pollution = not any("刚造" in c for c in aya_mems)
    passed = isolated and no_cross_pollution
    detail = (f"帮亚雅信任 > 骗刚造信任: {isolated} "
              f"(亚雅={t_aya:+.2f}, 刚造={t_goro:+.2f}); "
              f"跨NPC不污染: {no_cross_pollution}")
    w.close()
    return ProbeResult("世界隔离探针", passed, detail)


def run_all_probes(verbose: bool = True) -> list[ProbeResult]:
    """跑全部六个探针 (需 LLM 可达), 返回结果列表。"""
    if not _llm_available():
        raise RuntimeError("LLM 端点不可达, 无法跑集成探针")
    npc, now = build_scenario()
    results = [
        probe_consistency(npc, now),
        probe_non_omniscience(now),
        probe_persistence(npc, now),
        probe_drift(npc, now),
        probe_first_person(npc, now),
        probe_world_isolation(now),
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
