"""NPC: 把记忆流、检索、反思、规划、反应、对话接成一个完整智能体。

自我 (所有玩家共享, 稳定):
  persona + 自我反思 + 世界记忆 (player_id=None)

面对玩家 p 的"面" (独立成流, 动态):
  对 p 的关系记忆 + 对 p 的关系反思 + 信任状态

行为 = π(persona, 对p的记忆, 对p的关系反思, 当前计划, 当前情境, p)

成本闸门 (论文 blog 里"问题一"的落地):
- 分级认知: 近处 NPC 走完整循环, 远处只压缩更新, 空闲只做记忆。
- 决策缓存: 相同情境复用反应, 命中缓存不重复调 LLM (精确键, 有上限)。
"""

from __future__ import annotations

from ..dialogue import DialogueManager
from ...models.embeddings import Embedder, HashEmbedder
from ...models.llm import LLMClient
from ...memory.store import MemoryStore
from ...world.social_contracts import Hearsay
from ..planning import PlanningEngine, PlanState
from ..planning.memory import previous_day_context, shared_world_context
from ..reacting import ReactionDecider, ReactionDecision
from ..reflection import ReflectionEngine

from .consolidation import consolidate_observations
from .context import decision_context, identity_belief, rumor_to_share
from .observation import describe_action, write_observation
from .persistence import (load_configuration, prepare_path, restore_runtime,
                          save_checkpoint)
from .reactions import ReactionCache
from .state import REFLECTION_THRESHOLD, RuntimeState


class NPC:
    def __init__(self, name: str, persona_traits: dict[str, float],
                 llm: LLMClient,
                 embedder: Embedder | None = None,
                 store: MemoryStore | None = None,
                 reflection_threshold: float = REFLECTION_THRESHOLD,
                 conflict_policy: str = "full",
                 evidence_types: tuple[str, ...] = ("observation",),
                 evidence_min_relevance: float = 0.0,
                 use_relationship: bool = True) -> None:
        self.name = name
        self.persona_traits = persona_traits
        self.embedder = embedder or HashEmbedder()
        self.llm = llm
        self.store = store or MemoryStore(self.embedder)
        # npc_name 注入: 关系反思兜底问题用本 NPC 真名 (无名退中性 "NPC")
        # 消融开关原样透传, 缺省全部 = 现行为 (定义见 EvalPlan.md)
        self.reflection = ReflectionEngine(self.llm, self.embedder, npc_name=name,
                                           evidence_types=evidence_types,
                                           conflict_policy=conflict_policy,
                                           evidence_min_relevance=evidence_min_relevance)
        self.planner = PlanningEngine(self.llm)
        self.decider = ReactionDecider(self.store, self.llm,
                                       use_relationship=use_relationship)
        self.dialogue = DialogueManager(self.llm, self.store, persona_traits,
                                        name=name)

        self._runtime = RuntimeState(reflection_threshold=reflection_threshold)
        self.plan_state = PlanState()
        self._reactions = ReactionCache()

    def _advance(self, now: float) -> None:
        self._runtime.advance(now, self.forget)

    # ---------------------------------------------------------------- 遗忘
    def forget(self, now: float) -> list[int]:
        """时间遗忘清扫 (部分衰减降权, 不删除): 下调久未访问记忆的 importance,
        渐近到 MIN_IMPORTANCE, 返回被降权的 id。记忆保留, 只是检索权重降低。

        - 原始观察最先降权 (~2 天半衰期), 反思与情节摘要 ~1 周、身份信念 ~2 周,
          计划隔夜即降权。
        - 被有效反思引用为证据的观察受保护 (已固化为高阶认知, 不降权)。
        - 被回忆过 (last_accessed) / merge 刷新的记忆衰减更慢, 抗遗忘。
        注: 记忆不再删除, 故 LLM 判定的信任度不再随遗忘向 0 回归 (它仍能看到
        久远帮助/背叛的内容); 想让它随时间淡化, 需把降权后的权重一并喂给 LLM。
        """
        return self.store.decay_and_forget(now)

    # ---------------------------------------------------------------- 观察
    def observe(self, content: str, now: float,
                player_id: str | None = None,
                hearsay: bool = False, hop: int = 0,
                importance: float | None = None) -> int:
        """观察先去重再打分；仅新增共享观察驱动自我反思累积。"""
        self._advance(now)
        result = write_observation(self.store, self.llm, content, now,
                                   player_id, hearsay, hop, importance)
        if result.created:
            self._runtime.record_observation(result.importance, player_id)
        return result.memory_id

    def perceive_action(self, player_name: str, action: str, now: float) -> int:
        """按近期关系观察生成描述，再走统一观察入口。"""
        self._advance(now)
        content = describe_action(self.store, self.llm, self.name, player_name, action)
        return self.observe(content, now, player_id=player_name)

    # ---------------------------------------------------------------- 反思
    def maybe_reflect_self(self, now: float) -> list[int]:
        """重要性累积超阈值时触发自我反思 (阈值可配置, 默认 150 同论文)。"""
        if self._runtime.importance_accum < self._runtime.reflection_threshold:
            return []
        ids = self.reflection.reflect_self(self.store, now)
        self._runtime.importance_accum = 0.0
        # F4-5: 共享自我反思/identity 也要能被后续世界观察推翻 (此前冲突检查
        # 只按玩家扫关系反思, 自我/身份信念永不过期)。按共享证据签名门控,
        # 没有新观察/episode 时零 judge_conflict 调用。
        self.check_shared_conflicts(now)
        return ids

    def reflect_relationship(self, player_id: str, now: float) -> list[int]:
        """对某玩家做关系反思并检查冲突失效。"""
        self._advance(now)
        ids = self.reflection.reflect_relationship(self.store, player_id, now)
        self.reflection.check_conflicts(self.store, player_id, now)
        return ids

    def maybe_reflect_relationship(self, player_id: str, now: float) -> list[int]:
        """只对 full 档的新关系观察反思；成功后再推进反思水位。"""
        if self._runtime.tier != "full":
            return []
        obs_count = len(self.store.all_valid(player_id=player_id,
                                             types=["observation"]))
        if obs_count <= self._runtime.reflected_obs.get(player_id, 0):
            return []
        ids = self.reflect_relationship(player_id, now)
        self._runtime.reflected_obs[player_id] = obs_count
        return ids

    def reflect_identity(self, now: float) -> list[int]:
        """身份层信念 (M3): 跨玩家泛化, 写共享流 (type=identity)。显式触发。"""
        self._advance(now)
        return self.reflection.reflect_identity(self.store, now)

    def check_shared_conflicts(self, now: float) -> list[int]:
        """检查共享自我/identity 反思是否被更晚的世界证据推翻 (F4-5)。

        成本门控: 以"共享未固化观察 + episode"的 (条数, 最新时间戳) 为签名;
        签名未变说明没有新证据, 直接返回, 不再为同一批反思重复判矛盾。
        这也让 conflict_cache 的 512 上限不再被世界模拟的每步扫描打满。
        """
        evidence = (
            self.store.all_valid(shared=True, types=["observation"],
                                 consolidated=False)
            + self.store.all_valid(shared=True, types=["episode"]))
        sig = (len(evidence), max((m.timestamp for m in evidence), default=0.0))
        if sig == self._runtime.shared_conflict_sig:
            return []
        self._runtime.shared_conflict_sig = sig
        return self.reflection.check_conflicts(self.store, None, now, shared=True)

    def consolidate(self, now: float) -> list[int]:
        """固化成功后将新情节作为共享冲突检查的触发信号。"""
        self._advance(now)
        ids = consolidate_observations(self.store, self.llm, now)
        if ids:
            self.check_shared_conflicts(now)
        return ids

    # ---------------------------------------------------------------- 对话
    def speak(self, player_id: str, utterance: str, now: float,
              remember: bool = True,
              record_utterance: bool = True) -> str:
        """对玩家发言作出回应 (非全知, 只用自己记忆流), 默认把对话写入记忆。

        remember: 是否把本轮对话写进该玩家的关系面 (缺省 True)。单 NPC API
          (`npc.speak`) 没有世界层帮忙回流, 不写就"说完就忘"; 世界层可在已经
          用 perceive_action 观察过对方话语时传 record_utterance=False 防双写。
        record_utterance: 是否记录对方这句话。False 时只记录自己的回复
          (世界层 talk 路径用: 对方话语已由 perceive_action 观察入库)。
        """
        # 近处: 仅当该玩家出现新观察时才重跑关系反思 (否则反思无限增殖、
        # 信任度随反复反思漂移)。已有反思足以指导本次对话。
        self._advance(now)
        self.maybe_reflect_relationship(player_id, now)
        # 先拿到回复, 再写记忆: 本轮反思不该把"刚听到的这句话"当作旧证据。
        reply = self.dialogue.reply(player_id, utterance, now)
        if remember and record_utterance and utterance:
            self.observe(f"{player_id} 对我说: {utterance}", now,
                         player_id=player_id)
        if remember and reply:
            self.observe(f"我对 {player_id} 说: {reply}", now,
                         player_id=player_id)
        return reply

    # ---------------------------------------------------------------- 反应
    def react(self, event: str, player_id: str, now: float,
              current_plan: str | None = None) -> ReactionDecision:
        """按当前计划和关系响应事件；完整反应缓存归 NPC 所有。"""
        self._advance(now)
        plan = self.plan_state.context(now, explicit=current_plan)
        return self._reactions.decide(self.decider, event, player_id,
                                      self.persona_traits, plan,
                                      lambda: self.tier == "full")

    # ---------------------------------------------------------------- 规划
    def generate_daily_plan(self, previous_day: str, date: str, now: float) -> list[int]:
        """生成日计划并存入记忆流, 设为当前计划。

        计划在世界背景下生成: 取 NPC 近期观察 (含世界事件) 作为 context 喂给
        generate_plan, 让计划反映所处世界 (如持眼者逢眼狩令会规划躲避), 而非
        只靠人格+前一天活动生成岁月静好的日程。
        """
        self._advance(now)
        # L2: previous_day 应是前一天的**真实活动**, 而非 0-based 天数标签
        # ("第1天"其实是第二天, 对 LLM 无意义)。库里的昨日计划记忆就是"昨天干
        # 了什么" (新一天计划经 M4 失效替换前它们仍 valid)。首日无计划时退回
        # 调用方传入的标签。
        previous_day = previous_day_context(self.store, previous_day)
        # 世界背景只用共享流观察: 关系观察属于某个玩家的面, 不能进共享 plan
        # 的生成上下文 (否则 A 的秘密会随 plan 泄漏给 B)。E2: shared=True 是
        # "只取 NULL 流", player_id=None 是"不过滤", 二者不能混。
        context = shared_world_context(self.store)
        ids, blocks = self.planner.make_daily_plan(self.store, self.persona_traits,
                                                   previous_day, date, now, context=context)
        self.plan_state.replace(blocks)
        return ids

    def replan(self, now: float, interruption: str,
               interruption_player: str | None = None) -> list[int]:
        """反应后从当前时刻重规划后续。

        interruption_player: 中断来源玩家/实体。非 None 时把"计划被打断"观察
        写进该实体的关系面; None 写共享流。避免"被 Aria 攻击了"这类私有事件
        作为共享记忆被其他玩家检索到。
        """
        self._advance(now)
        # E14: 重规划也带世界背景 (近期观察), 同 generate_daily_plan —— 被打断后
        # 仍要在眼狩令等世界背景下重排剩余日程, 而非"岁月静好"。只取共享流。
        context = shared_world_context(self.store)
        ids, blocks = self.planner.replan_from_now(
            self.store, self.persona_traits, now, interruption,
            context=context, interruption_player=interruption_player)
        self.plan_state.replace(blocks, interruption=interruption)
        return ids

    # ---------------------------------------------------------------- 认知档位
    def set_tier(self, tier: str) -> None:
        """分级认知: full / compressed / idle。"""
        self._runtime.set_tier(tier)

    @property
    def tier(self) -> str:
        """当前认知档位；通过 set_tier 修改。"""
        return self._runtime.tier

    def clear_cache(self) -> None:
        """先清完整反应，再清事件评分和关系信任缓存。"""
        self._reactions.clear()
        self.decider.clear_cache()

    def cache_sizes(self) -> dict[str, int]:
        return {"decisions": self._reactions.size, **self.decider.cache_sizes()}

    @property
    def game_time(self) -> float:
        return self._runtime.game_time

    def runtime_state(self) -> RuntimeState:
        """返回运行状态副本；修改副本不会改变 NPC。"""
        return self._runtime.snapshot()

    # ---------------------------------------------------------------- 统计
    def memory_count(self, player_id: str | None = None) -> int:
        return self.store.count(player_id)

    def trust_toward(self, player_id: str) -> float:
        return self.decider.relationship_trust(player_id)

    def has_relationship(self, player_id: str) -> bool:
        return bool(self.store.all_valid(player_id=player_id))

    def rumor_to_share(self, query: str, now: float) -> Hearsay | None:
        return rumor_to_share(self.store, query, now)

    def decision_context(self, visible_entities: set[str]) -> str:
        return decision_context(self.store, visible_entities)

    def identity_belief(self) -> str:
        return identity_belief(self.store)

    # ---------------------------------------------------------------- 持久化
    @classmethod
    def create(cls, name: str, persona_traits: dict[str, float],
               llm: LLMClient, embedder: Embedder | None = None,
               data_dir: str = "data",
               reflection_threshold: float = REFLECTION_THRESHOLD) -> "NPC":
        """创建或加载一个持久化 NPC。

        记忆流与元数据存于 data_dir/<name>.db (一个 NPC 一个库)。
        不存在则新建并写入元数据; 已存在则等价于 load()。
        reflection_threshold: 重要性累积到多少触发自我反思 (默认 150 同论文,
        调低可让反思更频繁 —— 供世界模拟等场景使用)。
        """
        path, exists = prepare_path(name, data_dir)
        if exists:
            return cls.load(path, llm, embedder=embedder,
                            reflection_threshold=reflection_threshold)
        embedder = embedder or HashEmbedder()
        npc = cls(name, persona_traits, llm=llm, embedder=embedder,
                  store=MemoryStore(embedder, path=path),
                  reflection_threshold=reflection_threshold)
        npc._runtime.data_path = path
        npc.save()
        return npc

    @classmethod
    def load(cls, path: str, llm: LLMClient,
             embedder: Embedder | None = None,
             reflection_threshold: float | None = None) -> "NPC":
        """从 .db 文件加载一个已持久化的 NPC (记忆流 + 元数据全部恢复)。

        reflection_threshold 缺省时用库内存的值 (旧库无该字段则回退默认 150)。
        """
        embedder = embedder or HashEmbedder()
        store = MemoryStore(embedder, path=path)
        meta, threshold = load_configuration(store, path, reflection_threshold)
        npc = cls(meta["name"], meta["persona_traits"], llm=llm,
                  embedder=embedder, store=store,
                  reflection_threshold=threshold)
        npc._runtime.data_path = path
        npc.plan_state = restore_runtime(store, npc._runtime)
        return npc

    def save(self) -> None:
        """记忆即时落库；另按既有键保存 NPC 元数据及部分运行状态。"""
        save_checkpoint(self.store, self.name, self.persona_traits,
                        self._runtime, self.plan_state)

    def checkpoint_state(self) -> dict:
        """一致检查点专用；旧 save/load 的恢复范围保持独立。"""
        from dataclasses import asdict
        runtime = asdict(self._runtime)
        runtime.pop("data_path")
        return {
            "name": self.name, "persona_traits": dict(self.persona_traits),
            "configuration": {
                "reflection_threshold": self._runtime.reflection_threshold,
                "conflict_policy": self.reflection.conflict_policy,
                "evidence_types": list(self.reflection.evidence_types),
                "evidence_min_relevance": self.reflection.evidence_min_relevance,
                "use_relationship": self.decider.use_relationship,
            },
            "runtime": runtime,
            "plan": {"blocks": self.plan_state.saved_blocks(),
                     "interruption": self.plan_state.interruption},
        }

    @classmethod
    def from_checkpoint(cls, path: str, state: dict, llm: LLMClient,
                        embedder: Embedder | None = None) -> "NPC":
        embedder = embedder or HashEmbedder()
        store = MemoryStore(embedder, path=path)
        try:
            npc = cls(state["name"], dict(state["persona_traits"]), llm,
                      embedder=embedder, store=store, **state["configuration"])
            runtime = dict(state["runtime"])
            if runtime.get("shared_conflict_sig") is not None:
                runtime["shared_conflict_sig"] = tuple(runtime["shared_conflict_sig"])
            npc._runtime = RuntimeState(**runtime, data_path=path)
            npc.plan_state = PlanState([tuple(block) for block in state["plan"]["blocks"]],
                                       state["plan"]["interruption"])
            return npc
        except Exception:
            store.close()
            raise
