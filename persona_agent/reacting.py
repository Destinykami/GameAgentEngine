"""反应决策: 决定 NPC 是否响应环境事件, 以及响应后如何权衡。

核心是把"目标持续性 vs 行为灵活性"的权衡显式化为效用函数:

    U(a) = w_social · V_social(a) + w_goal · V_goal(a) − C_interrupt(a)

- w_social / w_goal 来自人格特质 (social / goal_oriented)。
- V_social / V_goal / C_interrupt 由 **LLM 判断** (score_event), 对任意事件
  (含没枚举过的) 都能给出价值, 取代了原来的关键词死表。判断结果按
  (事件, 计划) 缓存, 同一情境不重复调 LLM —— 反应是高频路径, 必须控成本。
- 关系状态 (对当前玩家的信任度) 调制 w_social: 信任的人的邀请更可能被接受。

这正是"千人千面"在反应层的体现: 同一个邀请, 对信任的友善玩家接受,
对警惕的玩家拒绝。
"""

from __future__ import annotations

from dataclasses import dataclass

from .llm import LLMClient
from .memory import MemoryStore

# 信任判断的输入窗口 (F2-4): 关系流会随交互无限增长, 全量塞 prompt 会让 token
# 线性膨胀并最终撞上下文上限。保留"高阶认知 + 近期观察"的窗口:
#   - reflection/identity/episode 最多 10 条 (信念/泛化/情节, 优先)
#   - observation 最多 20 条 (近期证据)
# 关系流较短时行为不变; 超窗时旧观察被排除 (episode 应承担长期凝练)。
JUDGE_TRUST_MAX_MEMORIES = 30


@dataclass
class ReactionDecision:
    react: bool
    action: str
    utility: float
    reason: str


class ReactionDecider:
    """基于人格 + 关系状态 + 当前计划 + LLM 事件价值判断的反应决策。"""

    def __init__(self, store: MemoryStore, llm: LLMClient,
                 use_relationship: bool = True) -> None:
        self._store = store
        self._llm = llm
        # 信任调制开关 (消融, 缺省 True = 现行为): False 时 trust_mod 钉死 1.0,
        # 同一事件对所有玩家同一效用 —— "无关系权重的效用决策" 消融臂。
        self._use_relationship = use_relationship
        # 事件价值缓存: (事件文本, 当前计划) → (v_social, v_goal, c_interrupt)。
        # 反应是高频路径, 同一情境不重复调 LLM。
        self._value_cache: dict[tuple[str, str], tuple[float, float, float]] = {}
        # 信任度缓存: 玩家 → (信任值, 关系记忆签名)。签名 = (条数, 最新时间戳),
        # 只有该玩家的关系记忆真正变化 (新增观察/反思、被遗忘) 才重判。
        # 信任是高频读取 (react 建缓存键就要用), 必须缓存, 否则每次都烧 LLM。
        self._trust_cache: dict[str, tuple[float, tuple]] = {}

    # -------------------------------------------------------- 关系信任度
    def relationship_trust(self, player_id: str) -> float:
        """对该玩家的信任度 -1..1, 由 LLM 基于关系记忆**内容**判断 (签名缓存)。

        取代关键词词表计数: LLM 能理解"搭把手"=帮、"放鸽子"=背叛等花样措辞。
        信任是**持久的关系认知**: 判断只看关系记忆的内容 (帮过/背叛过),
        刻意**不看 importance** —— 遗忘只降权不删除, 久远的帮助/背叛仍是
        认知, 不会因"久远"而清零。故信任度不随遗忘淡化。
        关系记忆不变时命中缓存 (签名 = 条数+最新时间戳), 零 LLM 成本。
        置信度不进签名: 衰减只发生在 check_conflicts, 而它必由新观察触发
        (speak 门控), 新观察已改签名 —— 所以签名未变 ⟹ 置信度未变, 缓存安全。

        E2: player_id=None 是"无玩家" (世界事件, 如火灾), 不存在"对 None 的信任
        度" —— 旧实现 all_valid(None) 拿全玩家流, 把不同玩家的关系记忆合在一起
        判出一个伪信任度还写进缓存。直接返回中性 0.0。
        """
        if player_id is None:
            return 0.0
        rel = self._store.all_valid(player_id=player_id)
        if not rel:
            return 0.0
        sig = (len(rel), max(m.timestamp for m in rel))
        cached = self._trust_cache.get(player_id)
        if cached is not None and cached[1] == sig:
            return cached[0]
        # F2-4: 高阶认知优先 + 近期观察填满窗口, 总数不超过
        # JUDGE_TRUST_MAX_MEMORIES; 缓存签名仍按全量关系流变化失效。
        high = [m for m in rel
                if m.type in ("reflection", "identity", "episode")]
        obs = [m for m in rel if m.type == "observation"]

        def _recent(items):
            return sorted(items, key=lambda m: (m.timestamp, m.id or 0),
                          reverse=True)

        selected = (_recent(high)[:10]
                    + _recent(obs)[:JUDGE_TRUST_MAX_MEMORIES - 10])
        # F4-2: 传闻在信任判断里显式标注跳数; 亲见不注水。LLM 据此降权,
        # 避免"听来的一句话"与亲眼所见同权决定信任。
        mems = [(m.type,
                 (f"[传闻{m.hop}跳] {m.content}" if m.hearsay else m.content),
                 m.confidence)
                for m in selected]
        trust = self._llm.judge_trust(mems, player_id)
        self._trust_cache[player_id] = (trust, sig)
        return trust

    # -------------------------------------------------------- 反应决策
    def decide(self, event: str, player_id: str,
               persona_traits: dict[str, float],
               current_plan: str = "") -> ReactionDecision:
        """决定是否响应事件并给出行动。事件价值由 LLM 判断 (带缓存)。"""
        v_social, v_goal, c_interrupt = self._score_event(
            event, persona_traits, current_plan)
        trust = self.relationship_trust(player_id)
        # 信任度调制社交权重: 信任 → 更愿社交; 警惕/背叛 → 社交价值大幅打折。
        # trust∈[-1,1] → [0, 2], 背叛者(trust≈-1)的社交价值被压到几乎为零。
        trust_mod = max(0.0, 1.0 + trust) if self._use_relationship else 1.0
        w_social = persona_traits.get("social", 0.5) * trust_mod
        w_goal = persona_traits.get("goal_oriented", 0.5)

        utility = w_social * v_social + w_goal * v_goal - c_interrupt
        react = utility >= 0.0
        if react:
            action = f"接受并参与: {event}"
            reason = (f"效用 {utility:.2f} ≥ 0 (LLM判价值 社交{v_social:.0f}/"
                      f"目标{v_goal:.0f}/打断{c_interrupt:.0f}, "
                      f"社交权重{w_social:.2f}, 目标权重{w_goal:.2f}, 信任{trust:+.2f})")
        else:
            action = f"婉拒: {event}, 继续当前安排"
            reason = (f"效用 {utility:.2f} < 0 (LLM判价值 社交{v_social:.0f}/"
                      f"目标{v_goal:.0f}/打断{c_interrupt:.0f}, "
                      f"目标价值高或信任不足)")
        return ReactionDecision(react=react, action=action,
                                utility=utility, reason=reason)

    # --------------------------------------------------------------- 内部
    def _score_event(self, event: str, persona_traits: dict[str, float],
                     current_plan: str) -> tuple[float, float, float]:
        """LLM 判断事件价值, 按 (事件, 计划) 缓存。"""
        key = (event, current_plan)
        if key in self._value_cache:
            return self._value_cache[key]
        val = self._llm.score_event(event, persona_traits, current_plan)
        self._value_cache[key] = val
        return val

    def clear_cache(self) -> None:
        self._value_cache.clear()
        self._trust_cache.clear()
