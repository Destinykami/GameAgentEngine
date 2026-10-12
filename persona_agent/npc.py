"""NPC: 把记忆流、检索、反思、规划、反应、对话接成一个完整智能体。

自我 (所有玩家共享, 稳定):
  persona + 自我反思 + 世界记忆 (player_id=None)

面对玩家 p 的"面" (独立成流, 动态):
  对 p 的关系记忆 + 对 p 的关系反思 + 信任状态

行为 = π(persona, 对p的记忆, 对p的关系反思, 当前计划, 当前情境, p)

成本闸门 (论文 blog 里"问题一"的落地):
- 分级认知: 近处 NPC 走完整循环, 远处只压缩更新, 空闲只做记忆。
- 语义缓存: 相似情境复用反应, 命中缓存不重复调 LLM。
"""

from __future__ import annotations

from .dialogue import DialogueManager
from .embeddings import Embedder, HashEmbedder
from .llm import LLMClient
from .memory import MemoryRecord, MemoryStore
from .planning import PlanningEngine
from .reacting import ReactionDecider, ReactionDecision
from .reflection import ReflectionEngine

REFLECTION_THRESHOLD = 150.0   # 重要性累积阈值, 触发反思 (同论文)


class NPC:
    def __init__(self, name: str, persona_traits: dict[str, float],
                 llm: LLMClient,
                 embedder: Embedder | None = None,
                 store: MemoryStore | None = None) -> None:
        self.name = name
        self.persona_traits = persona_traits
        self.embedder = embedder or HashEmbedder()
        self.llm = llm
        self.store = store or MemoryStore(self.embedder)
        self.reflection = ReflectionEngine(self.llm)
        self.planner = PlanningEngine(self.llm)
        self.decider = ReactionDecider(self.store)
        self.dialogue = DialogueManager(self.llm, self.store, persona_traits)

        # 成本闸门状态
        self._importance_accum = 0.0
        self._current_plan = ""
        self._tier: str = "full"        # full | compressed | idle
        self._cache: dict[str, str] = {}
        # 每玩家"上次关系反思时的观察数": 用于门控, 避免每次对话都重跑反思
        # 导致反思无限增殖、信任度漂移 (只有出现新观察才值得再反思)
        self._reflected_obs: dict[str, int] = {}

    # ---------------------------------------------------------------- 观察
    def observe(self, content: str, now: float,
                player_id: str | None = None) -> int:
        """记录一条观察 (世界事件或关系事件), 按玩家参照系打重要性分。"""
        importance = self.llm.score_importance(content, player_id)
        rec = MemoryRecord(content=content, timestamp=now, type="observation",
                           player_id=player_id, importance=importance)
        mem_id = self.store.add(rec)
        # 累积重要性, 驱动反思 (近处才累积, 远处/空闲不累积)
        if self._tier != "idle":
            self._importance_accum += importance
        return mem_id

    # ---------------------------------------------------------------- 反思
    def maybe_reflect_self(self, now: float) -> list[int]:
        """重要性累积超阈值时触发自我反思。"""
        if self._importance_accum < REFLECTION_THRESHOLD:
            return []
        ids = self.reflection.reflect_self(self.store, now)
        self._importance_accum = 0.0
        return ids

    def reflect_relationship(self, player_id: str, now: float) -> list[int]:
        """对某玩家做关系反思并检查冲突失效。"""
        ids = self.reflection.reflect_relationship(self.store, player_id, now)
        self.reflection.check_conflicts(self.store, player_id, now)
        return ids

    # ---------------------------------------------------------------- 对话
    def speak(self, player_id: str, utterance: str, now: float) -> str:
        """对玩家发言作出回应 (非全知, 只用自己记忆流)。"""
        # 近处: 仅当该玩家出现新观察时才重跑关系反思 (否则反思无限增殖、
        # 信任度随反复反思漂移)。已有反思足以指导本次对话。
        if self._tier == "full":
            obs_count = len(self.store.all_valid(player_id=player_id,
                                                 types=["observation"]))
            if obs_count > self._reflected_obs.get(player_id, 0):
                self.reflect_relationship(player_id, now)
                self._reflected_obs[player_id] = obs_count
        return self.dialogue.reply(player_id, utterance, now)

    # ---------------------------------------------------------------- 反应
    def react(self, event: str, player_id: str, now: float,
              current_plan: str | None = None) -> ReactionDecision:
        """决定是否响应事件。带语义缓存: 相似情境复用反应。"""
        plan = current_plan if current_plan is not None else self._current_plan
        # 语义缓存: 按事件+玩家+关系档位缓存 (关系档位粗粒度, 避免过度失效)
        trust = self.decider.relationship_trust(player_id)
        trust_bucket = round(trust * 2) / 2   # -1..1 量化到 0.5
        cache_key = f"{event}|{player_id}|{trust_bucket}|{plan[:20]}"
        if cache_key in self._cache:
            cached = self._cache[cache_key]
            d = ReactionDecision(react=("接受" in cached), action=cached,
                                 utility=0.0, reason="语义缓存命中")
            return d
        decision = self.decider.decide(event, player_id, self.persona_traits, plan)
        if self._tier == "full":
            self._cache[cache_key] = decision.action
        return decision

    # ---------------------------------------------------------------- 规划
    def generate_daily_plan(self, previous_day: str, date: str, now: float) -> list[int]:
        """生成日计划并存入记忆流, 设为当前计划。"""
        ids = self.planner.make_daily_plan(self.store, self.persona_traits,
                                           previous_day, date, now)
        self._current_plan = "日计划已生成"
        return ids

    def replan(self, now: float, interruption: str) -> list[int]:
        """反应后从当前时刻重规划后续。"""
        ids = self.planner.replan_from_now(self.store, self.persona_traits,
                                           now, interruption)
        self._current_plan = interruption
        return ids

    # ---------------------------------------------------------------- 认知档位
    def set_tier(self, tier: str) -> None:
        """分级认知: 近处 full, 远处 compressed, 空闲 idle。"""
        assert tier in ("full", "compressed", "idle")
        self._tier = tier

    def clear_cache(self) -> None:
        self._cache.clear()

    # ---------------------------------------------------------------- 统计
    def memory_count(self, player_id: str | None = None) -> int:
        return self.store.count(player_id)

    def trust_toward(self, player_id: str) -> float:
        return self.decider.relationship_trust(player_id)
