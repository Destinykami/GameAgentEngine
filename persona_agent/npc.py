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

import os
from collections import OrderedDict

from .dialogue import DialogueManager
from .embeddings import Embedder, HashEmbedder
from .llm import LLMClient
from .memory import HEARSAY_MAX_HOP, MemoryRecord, MemoryStore
from .social_contracts import Hearsay
from .planning import PlanningEngine
from .reacting import ReactionDecider, ReactionDecision
from .reflection import ReflectionEngine

REFLECTION_THRESHOLD = 150.0   # 重要性累积阈值, 触发反思 (同论文)
SWEEP_INTERVAL = 6.0           # 游戏时钟每推进 6h 自动做一次遗忘清扫
NPC_CACHE_LIMIT = 512          # 决策缓存条数上限 (F6-2, 防长模拟无界增长)


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
        self._reflection_threshold = reflection_threshold   # 重要性累积到多少触发自我反思 (可调)
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

        # 成本闸门状态
        # 自我反思触发器: 只由共享流观察累加 (关系观察走 _reflected_obs 门控)
        self._importance_accum = 0.0
        self._current_plan = ""        # 反应后重规划的中断原因覆盖 (如"处理火灾"), 优先于日计划块
        self._plan_blocks: list[tuple[int, int, str]] = []   # 当日计划块 (start, end, activity)
        self._tier: str = "full"        # full | compressed | idle
        # 决策缓存: 键 → 完整 ReactionDecision (F5-2: 不再只存 action 字符串,
        # 否则缓存命中时要从自然语言反解析 react/utility, 事件文本含"接受"就会
        # 把婉拒误判成接受)。F6-2: OrderedDict + 上限, 长模拟不无界增长。
        self._cache: OrderedDict[str, ReactionDecision] = OrderedDict()
        # 每玩家"上次关系反思时的观察数": 用于门控, 避免每次对话都重跑反思
        # 导致反思无限增殖、信任度漂移 (只有出现新观察才值得再反思)
        self._reflected_obs: dict[str, int] = {}
        # F4-5 成本门控: 共享冲突检查只在共享证据 (未固化观察/episode) 变化时跑,
        # 不在每次 maybe_reflect_self 都扫 (否则 judge_conflict 成为最大成本项)。
        self._shared_conflict_sig: tuple | None = None
        # 持久化: 文件库路径 + 游戏内时钟 (小时, 单调递增)
        self._data_path: str | None = None
        self._game_time: float = 0.0
        self._last_sweep: float | None = None   # 上次遗忘清扫的游戏时刻

    def _advance(self, now: float) -> None:
        """推进游戏时钟 (取 max, 容忍乱序事件); 到点自动清扫遗忘。"""
        if now > self._game_time:
            self._game_time = now
        # 背景遗忘: 每 SWEEP_INTERVAL 游戏小时清扫一次 (纯本地计算, 零 LLM)
        if self._last_sweep is None:
            self._last_sweep = now
        elif now - self._last_sweep >= SWEEP_INTERVAL:
            self.forget(now)
            self._last_sweep = now

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
        """记录一条观察 (世界事件或关系事件), 按玩家参照系打重要性分。

        观察层去重: 同玩家的近义观察 (>= 0.92) 合并进已有记录 ——
        刷新 last_accessed (重复发生强化记忆) 并提升 importance,
        不新增。防止事件重放灌水: 信任度不再被重复计分,
        重要性累积不再被重复观察反复抬高。返回 (可能已存在的) 记忆 id。

        hearsay/hop (S4, 缺省亲见): 传闻观察标记传播身份, 检索按 hop 打折。
        importance: 预打好的重要性 (世界事件对同一文本只打一次分时由调用方传入);
        None = 本 NPC 自己调 score_importance。
        """
        self._advance(now)
        # F2-2: 先去重再打分。重复在场走 merge 分支, 不需要 importance
        # (merge 已不读取它), 这样重复观察零 LLM 成本; 旧顺序让 0.92 去重
        # 只能省存储, 省不掉每次 observe 的 score_importance 调用。
        dup = self.store.find_similar_observation(content, player_id)
        if dup is not None:
            # 合并 = 时间窗内 +1 强化 (见 memory.MERGE_REINFORCE_INTERVAL),
            # 不传 importance —— 事件重要性已在首次入库时计入, 重复合并再加
            # 全量是双重计分 (M6 死参数已删)。
            self.store.merge_observation(dup.id, now,
                                         new_hearsay=hearsay, new_hop=hop,
                                         new_content=content)
            # E7: 合并的重复是零新信息, 不累积到反思触发器。反思该由**新信息**
            # 驱动, 不是旧信息的反复强化 —— 世界层每步 perceive→observe→去重合并
            # 重放位置观察, 若 merge 分支仍累加原始 importance (世界感知常 8-10),
            # 零新信息几步就顶满反思阈值, 产出"1 条观察、6 步 6 条反思"的膨胀
            # (E6 那张 48:9 反思表的直接生成机制)。强化已由 merge 的限速 +1
            # importance 承担 (抬高显著度, 检索排名上升), 那是显著度信号,
            # 不是反思信号。
            # 传闻重听同理: 合并保留原记录的 hop (不升级传播身份)。
            return dup.id
        if importance is None:
            importance = self.llm.score_importance(content, player_id)
        rec = MemoryRecord(content=content, timestamp=now, type="observation",
                           player_id=player_id, importance=importance,
                           hearsay=hearsay, hop=hop)
        mem_id = self.store.add(rec)
        # 累积重要性, 驱动**自我反思** (近处才累积, 远处/空闲不累积)。
        # 只累积共享流观察: reflect_self 只读 shared=True 观察 (E8), 关系观察
        # 若也累加, 会把 self 触发器打满却产出不了自我反思 (空转/重复烧 LLM);
        # 关系观察由 speak/flush_social 的 _reflected_obs 门控驱动关系反思。
        if self._tier != "idle" and player_id is None:
            self._importance_accum += importance
        return mem_id

    def perceive_action(self, player_name: str, action: str,
                        now: float) -> int:
        """NPC 观察玩家对它做的动作, 自己生成观察描述并记录。

        与 observe() (脚本写死观察内容) 不同: 这里脚本只提供原始动作
        (动词+对象, 如"帮藏眼"), NPC 结合自己的近期记忆用 LLM 把动作观察成
        第三人称描述 (LLM 生成), 再走 observe 记录 (打分/去重/累积)。
        观察内容由 NPC 自己产生, 不是脚本写死的。
        """
        self._advance(now)
        recent = [m.content for m in self.store.all_valid(
            player_id=player_name, types=["observation"])[-3:]]
        context = " | ".join(recent) if recent else ""
        content = self.llm.perceive_action(self.name, player_name, action, context)
        return self.observe(content, now, player_id=player_name)

    # ---------------------------------------------------------------- 反思
    def maybe_reflect_self(self, now: float) -> list[int]:
        """重要性累积超阈值时触发自我反思 (阈值可配置, 默认 150 同论文)。"""
        if self._importance_accum < self._reflection_threshold:
            return []
        ids = self.reflection.reflect_self(self.store, now)
        self._importance_accum = 0.0
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
        if self._tier != "full":
            return []
        obs_count = len(self.store.all_valid(player_id=player_id,
                                             types=["observation"]))
        if obs_count <= self._reflected_obs.get(player_id, 0):
            return []
        ids = self.reflect_relationship(player_id, now)
        self._reflected_obs[player_id] = obs_count
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
        if sig == self._shared_conflict_sig:
            return []
        self._shared_conflict_sig = sig
        return self.reflection.check_conflicts(self.store, None, now, shared=True)

    def consolidate(self, now: float) -> list[int]:
        """夜间记忆固化 (M1): 把当天未固化的原始观察按流压缩成情节摘要 (episode),
        源观察标 consolidated (仍 valid 可检索, 退出冲突扫描)。

        - 按流分组 (共享流 + 各玩家面), 每流一次 LLM 调用, 产物 episode 留在
          同流 (冲突扫描按流进行, episode 必须和被吸收的观察同流才顶得替)。
        - 摘要置信度取源观察最低 confidence (保守: 摘要不比其原料更可信)。
        - 幂等: consolidated 观察不再被捡起, 同一天重跑不产生新 episode。
        - 显式触发 (世界层 consolidation 开关 + 每日时刻), 不进 observe 路径。
        """
        self._advance(now)
        day_start = now - 24.0
        new_ids: list[int] = []
        # 流分组 (确定性顺序): 共享流先, 各玩家面按名字排序。
        # E2 陷阱: all_valid(player_id=None) 是"不过滤"不是共享流 —— 共享流必须
        # shared=True, 否则共享流的循环会把全部观察 (含玩家面) 一次全吃掉。
        player_ids = sorted({m.player_id for m in
                             self.store.all_valid(types=["observation"])
                             if m.player_id is not None})
        for shared, pid in [(True, None)] + [(False, p) for p in player_ids]:
            obs = [m for m in self.store.all_valid(shared=shared, player_id=pid,
                                                   types=["observation"],
                                                   consolidated=False)
                   if m.timestamp >= day_start]
            if len(obs) < 2:   # 单条观察本身已是摘要, 无需压缩
                continue
            summary = self.llm.consolidate_observations(
                [m.content for m in obs], pid)
            if not summary or not summary.strip():
                continue
            # F4-2: episode 继承来源。任一条原料是传闻则标 hearsay; hop 取
            # 最远来源 (保守: 摘要的可信度不高于其最弱原料)。
            ep = MemoryRecord(content=summary.strip(), timestamp=now,
                              type="episode", player_id=pid,
                              evidence=[m.id for m in obs if m.id is not None],
                              confidence=min(m.confidence for m in obs),
                              base_confidence=min(m.confidence for m in obs),
                              importance=max(m.importance for m in obs),
                              hearsay=any(m.hearsay for m in obs),
                              hop=max((m.hop for m in obs if m.hearsay),
                                      default=0))
            ep_id = self.store.add(ep)
            self.store.mark_consolidated([m.id for m in obs])
            new_ids.append(ep_id)
        if new_ids:
            # episode 是新证据: 共享自我/identity 信念同样要过一遍冲突检查
            self.check_shared_conflicts(now)
        return new_ids

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
        """决定是否响应事件。带决策缓存: 相同情境复用反应。"""
        self._advance(now)
        # 计划上下文: 显式参数 > 当前时刻正在进行的计划块 > 重规划中断覆盖。
        # 不再用"日计划已生成"空话 —— score_event 需要知道 NPC 正忙什么才能
        # 判断目标契合度与打断代价。
        if current_plan is not None:
            plan = current_plan
        else:
            plan = self._current_activity(now) or self._current_plan
        # 决策缓存: 按事件+玩家+关系档位缓存 (关系档位粗粒度, 避免过度失效)。
        # F5-4: use_relationship=False 的消融臂不应计算 trust, 缓存键也不带
        # trust 维度 (固定 "-"), 否则同一事件仍会因信任不同而拆缓存。
        if self.decider.use_relationship:
            trust = self.decider.relationship_trust(player_id)
            trust_bucket = round(trust * 2) / 2   # -1..1 量化到 0.5
        else:
            trust_bucket = "-"
        cache_key = f"{event}|{player_id}|{trust_bucket}|{plan[:20]}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            self._cache.move_to_end(cache_key)   # LRU 命中提权
            # F5-2: 完整复用原决策 (react/action/utility), 只把 reason 换成
            # 缓存命中标记; 不再从 action 文本反解析"接受"。
            return ReactionDecision(react=cached.react, action=cached.action,
                                    utility=cached.utility,
                                    reason="决策缓存命中")
        decision = self.decider.decide(event, player_id, self.persona_traits, plan)
        if self._tier == "full":
            self._cache[cache_key] = decision
            self._cache.move_to_end(cache_key)
            while len(self._cache) > NPC_CACHE_LIMIT:
                self._cache.popitem(last=False)
        return decision

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
        plans = self.store.all_valid(types=["plan"])
        if plans:
            previous_day = "前一天活动: " + " | ".join(p.content for p in plans)
        # 世界背景只用共享流观察: 关系观察属于某个玩家的面, 不能进共享 plan
        # 的生成上下文 (否则 A 的秘密会随 plan 泄漏给 B)。E2: shared=True 是
        # "只取 NULL 流", player_id=None 是"不过滤", 二者不能混。
        recent = [m.content for m in self.store.all_valid(
            shared=True, types=["observation"])[-10:]]
        context = " | ".join(recent) if recent else ""
        ids, blocks = self.planner.make_daily_plan(self.store, self.persona_traits,
                                                   previous_day, date, now, context=context)
        self._plan_blocks = blocks       # 存块, 供 react 按当前时刻取"正在进行的计划"
        self._current_plan = ""          # 日计划接管"当前正忙", 清除重规划的中断覆盖
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
        recent = [m.content for m in self.store.all_valid(
            shared=True, types=["observation"])[-10:]]
        context = " | ".join(recent) if recent else ""
        ids, blocks = self.planner.replan_from_now(
            self.store, self.persona_traits, now, interruption,
            context=context, interruption_player=interruption_player)
        self._plan_blocks = blocks       # 重规划后的新块接管"当前正忙"
        self._current_plan = interruption   # 中断原因作兜底覆盖 (新块未覆盖此刻时生效)
        return ids

    # ---------------------------------------------------------------- 当前计划
    def _current_activity(self, now: float) -> str:
        """当前时刻正在进行的计划活动 (按 now 的当天小时匹配计划块)。

        计划块为 (start, end, activity), start/end 是当天小时; now 是单调递增的
        游戏内小时, 当天小时 = now % 24。匹配不到 (计划未覆盖此刻) 返回 ""。
        让 react 的 score_event 拿到"当前正忙的真实活动", 而非"日计划已生成"空话。
        """
        hour = now % 24
        for start, end, activity in self._plan_blocks:
            if start <= hour < end:
                return activity
        return ""

    # ---------------------------------------------------------------- 认知档位
    def set_tier(self, tier: str) -> None:
        """分级认知: 近处 full, 远处 compressed, 空闲 idle。"""
        assert tier in ("full", "compressed", "idle")
        self._tier = tier

    @property
    def tier(self) -> str:
        """当前认知档位；通过 set_tier 修改。"""
        return self._tier

    def clear_cache(self) -> None:
        """清空决策缓存与 Decider 的事件价值/信任缓存 (F6-9)。"""
        self._cache.clear()
        self.decider.clear_cache()

    # ---------------------------------------------------------------- 统计
    def memory_count(self, player_id: str | None = None) -> int:
        return self.store.count(player_id)

    def trust_toward(self, player_id: str) -> float:
        return self.decider.relationship_trust(player_id)

    def has_relationship(self, player_id: str) -> bool:
        return bool(self.store.all_valid(player_id=player_id))

    def rumor_to_share(self, query: str, now: float) -> Hearsay | None:
        """返回一条相关且尚可传播的传闻，不把记忆存储接口暴露给路由层。"""
        hits = self.store.retrieve(
            query=query, now=now, top_k=1, types=["observation"],
            hearsay_only=True, min_relevance=0.15, mark_accessed=False)
        if not hits or hits[0]["hop"] >= HEARSAY_MAX_HOP:
            return None
        hit = hits[0]
        return Hearsay(hit["content"], hit["player_id"], hit["hop"])

    def decision_context(self, visible_entities: set[str]) -> str:
        """自治决策只暴露共享记忆与可见对象的关系面，保留原末 5 条窗口。"""
        memories = [m.content for m in self.store.all_valid()
                    if m.player_id is None or m.player_id in visible_entities][-5:]
        return " | ".join(memories)

    def identity_belief(self) -> str:
        """最新有效共享身份信念；是否使用由调用方策略决定。"""
        beliefs = self.store.all_valid(shared=True, types=["identity"])
        return beliefs[-1].content if beliefs else ""

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
        os.makedirs(data_dir, exist_ok=True)
        path = os.path.join(data_dir, f"{name}.db")
        if os.path.exists(path):
            return cls.load(path, llm, embedder=embedder,
                            reflection_threshold=reflection_threshold)
        embedder = embedder or HashEmbedder()
        npc = cls(name, persona_traits, llm=llm, embedder=embedder,
                  store=MemoryStore(embedder, path=path),
                  reflection_threshold=reflection_threshold)
        npc._data_path = path
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
        meta = store.get_meta("npc")
        if not meta:
            raise ValueError(f"{path} 中没有 NPC 元数据 (不是 NPC 库)")
        threshold = (reflection_threshold
                     if reflection_threshold is not None
                     else meta.get("reflection_threshold", REFLECTION_THRESHOLD))
        npc = cls(meta["name"], meta["persona_traits"], llm=llm,
                  embedder=embedder, store=store,
                  reflection_threshold=threshold)
        npc._data_path = path
        npc._game_time = float(store.get_meta("game_time", 0.0))
        # F6-7: 恢复瞬态。旧库没有这两个 meta 时回退为空/空串 (旧行为)。
        reflected = store.get_meta("reflected_obs", {}) or {}
        npc._reflected_obs = {str(k): int(v) for k, v in reflected.items()}
        blocks = store.get_meta("plan_blocks", []) or []
        restored: list[tuple[int, int, str]] = []
        for b in blocks:
            if (isinstance(b, (list, tuple)) and len(b) == 3
                    and isinstance(b[0], (int, float))
                    and isinstance(b[1], (int, float))):
                restored.append((int(b[0]), int(b[1]), str(b[2])))
        npc._plan_blocks = restored
        npc._last_sweep = npc._game_time
        return npc

    def save(self) -> None:
        """把 NPC 元数据 (名称/人格/游戏时钟) 写入库。记忆流本身落库即持久。"""
        if not self.store.is_persistent():
            raise RuntimeError("该 NPC 使用 :memory: 库, 无法持久化 "
                               "(请用 NPC.create / NPC.load 创建)")
        self.store.set_meta("npc", {"name": self.name,
                                    "persona_traits": self.persona_traits,
                                    "reflection_threshold":
                                        self._reflection_threshold})
        self.store.set_meta("game_time", self._game_time)
        # F6-7: 瞬态 (关系反思门控/当前计划块) 一并持久化, 重载后不重复反思、
        # 不丢当前时刻的计划上下文。
        self.store.set_meta("reflected_obs", dict(self._reflected_obs))
        self.store.set_meta("plan_blocks",
                            [list(b) for b in self._plan_blocks])
        if self._data_path is None:
            self._data_path = self.store.db_path()
