"""反思生成编排；触发时机归 NPC，写入与冲突处理归独立组件。"""

from __future__ import annotations

from ...models.embeddings import Embedder
from .contracts import ConflictMemory, ReflectionMemory, ReflectionModel
from .conflicts import ConflictResolver
from .policies import (DEDUP_THRESHOLD, RELATIONSHIP_OBSERVATION_LIMIT,
                       RELATIONSHIP_EVIDENCE_CANDIDATES)
from .writing import ReflectionWriter


class ReflectionEngine:
    def __init__(self, llm: ReflectionModel,
                 embedder: Embedder | None = None,
                 dedup_threshold: float = DEDUP_THRESHOLD,
                 npc_name: str = "",
                 evidence_types: tuple[str, ...] = ("observation",),
                 conflict_policy: str = "full",
                 evidence_min_relevance: float = 0.0) -> None:
        self._llm = llm
        self._npc_name = npc_name
        self.evidence_types = tuple(evidence_types)
        self.conflict_policy = conflict_policy
        self.evidence_min_relevance = evidence_min_relevance
        self._writer = ReflectionWriter(embedder, dedup_threshold)
        self._conflicts = ConflictResolver(llm)

    def reflect_self(self, store: ReflectionMemory, now: float,
                     recent_n: int = 100) -> list[int]:
        """从最近的自我/世界记忆生成自我反思, 返回新记忆 id。"""
        # 只用真实观察生成问题与证据: 若把反思也纳入, 反思会拿别的反思当证据,
        # 一代代复述放大自己 (级联失控)。观察是唯一的"事实"来源。
        # E8: 只取共享流 (player_id IS NULL, 世界/自我观察) —— 自我反思回答"我
        # 是谁", 不该吃进某玩家的关系观察 (那是关系反思的料, 会产出"旅行者对我
        # 做了什么"的伪自我反思, 违反自我/面解耦)。旧实现 all_valid(None) 拿全
        # 玩家流, 正是这个污染 (E2 下游)。
        recent = store.all_valid(shared=True, types=["observation"])
        recent = recent[-recent_n:]
        if not recent:
            return []
        texts = [m.content for m in recent]
        # 过滤空白/非字符串问题 (L9, 与 M1 同族): [""] 这类"假问题"非空列表,
        # 旧判空拦不住, 空查询 (零向量) 会流进证据检索与洞察生成。自我反思有意
        # 不设兜底 (低价值路径允许静默跳过, 与关系反思的保面兜底不对称) —— 只补过滤。
        questions = [q for q in self._llm.reflection_questions(texts)
                     if isinstance(q, str) and q.strip()]

        new_ids: list[int] = []
        for q in questions:
            # mark_accessed=False: 证据检索只是"考虑候选", 不是"被回忆" —— 刷新
            # 遗忘锚点会让反思静默给 top_k 里没被引用的观察续命 (M7)。真正被引用
            # 为证据的观察由"被有效反思引用即保护"单独兜底, 不依赖此副作用。
            evidence = store.retrieve(query=q, now=now,
                                      shared=True, top_k=10,
                                      types=list(self.evidence_types),
                                      min_relevance=self.evidence_min_relevance,
                                      mark_accessed=False)
            ev_pairs = [(e["id"], e["content"]) for e in evidence]
            if not ev_pairs:
                continue
            for insight, ev_ids in self._llm.reflection_insights(ev_pairs, n=3):
                new_id = self._writer.save(
                    store, now, content=insight, evidence=ev_ids,
                    player_id=None, confidence=0.8, shared=True)
                if new_id is not None:
                    new_ids.append(new_id)
        return new_ids

    def reflect_relationship(self, store: ReflectionMemory, player_id: str,
                             now: float) -> list[int]:
        """对某玩家的关系记忆生成关系反思, 返回新记忆 id。"""
        rel = store.recent_relationship_observations(
            player_id, now, limit=RELATIONSHIP_OBSERVATION_LIMIT)
        if not rel:
            return []
        texts = [m.content for m in rel]
        # 过滤空白/非字符串问题: [""] 这类"假问题"非空列表, 旧判空拦不住, 会让
        # 空查询流进证据检索 (零向量) 和洞察生成。过滤后再判空, 兜底才不会被绕过。
        questions = [q for q in self._llm.reflection_questions(texts)
                     if isinstance(q, str) and q.strip()]
        if not questions:
            # 保"面"的 fail-safe: 问题生成形状漂移 (JSON 非数组) 时降级成一句通用
            # 问题, 让证据→洞察链至少跑一遍, 关系认知照常形成 —— 降级而非跳过。
            # 名字用本引擎所属 NPC (构造时注入), 无名退中性 "NPC", 不外泄 demo 名。
            who = self._npc_name or "NPC"
            questions = [f"{who} 和 {player_id} 的关系如何?"]

        new_ids: list[int] = []
        for q in questions:
            # 证据只用真实观察, 不用其他反思 → 切断"反思引用反思"的级联。
            # mark_accessed=False: 同 reflect_self, 候选证据不刷新遗忘锚点 (M7)。
            evidence = store.retrieve(query=q, now=now, player_id=player_id,
                                      top_k=10, include_player=player_id,
                                      types=list(self.evidence_types),
                                      min_relevance=self.evidence_min_relevance,
                                      mark_accessed=False,
                                      candidate_limit=RELATIONSHIP_EVIDENCE_CANDIDATES)
            ev_pairs = [(e["id"], e["content"]) for e in evidence]
            if not ev_pairs:
                continue
            for insight, ev_ids in self._llm.reflection_insights(ev_pairs, n=3):
                # 关系反思的置信度: 证据越多越高, 但有上限
                confidence = min(0.95, 0.5 + 0.1 * len(ev_ids))
                new_id = self._writer.save(
                    store, now, content=insight, evidence=ev_ids,
                    player_id=player_id, confidence=confidence, shared=False)
                if new_id is not None:
                    new_ids.append(new_id)
        return new_ids

    def reflect_identity(self, store: ReflectionMemory, now: float,
                         recent_n: int = 50) -> list[int]:
        """身份层信念 (M3): 跨玩家泛化 —— "综合我对待不同玩家的经历, 我是
        什么样的人, 今后该如何对待来往的人"。产物 type="identity", 写共享流
        (player_id=None), 对所有玩家生效。

        证据刻意**跨流**: 关系反思 (各玩家面, 泛化原料) + 共享流观察 (世界/
        自我经历)。这是 E8 "自我反思只吃共享流" 的有意例外 —— 身份信念要回答的
        正是"跨玩家的泛化", 只吃共享流会把不同玩家的经历排除在外, 泛化无从谈
        起。安全边界: 身份信念在独立 type 池, 证据约束链 (evidence_types 锁
        observation) 不会把 identity 当证据引用, 级联风险被类型隔离封死。
        """
        # 跨流证据: 各玩家面的关系反思 (泛化原料) + 共享流观察 (世界/自我经历)
        rel = store.all_valid(types=["reflection"])[-recent_n:]
        world_obs = store.all_valid(shared=True, types=["observation"])[-recent_n:]
        ev_pairs = [(m.id, m.content) for m in rel + world_obs if m.id is not None]
        if not ev_pairs:
            return []
        who = self._npc_name or "NPC"
        # 单一固定身份问题 (不生成问题: 身份反思问的就是这一件事, 生成问题只会
        # 漂移回"我最近做了什么"的伪身份反思)
        question = (f"综合{who}对待不同玩家的经历与所处世界, {who}是什么样"
                    f"的人, 今后该如何对待来往的人?")
        # 证据检索: 只从共享流 (世界/自我观察) 检索 —— 与 E8 "自我反思只吃共享
        # 流" 同向; 各玩家面的关系反思不走检索, 由 ev_pairs 直接注入当泛化原料。
        evidence = store.retrieve(query=question, now=now, top_k=10, shared=True,
                                  types=["observation"],
                                  min_relevance=self.evidence_min_relevance,
                                  mark_accessed=False)
        ev_ids = [(e["id"], e["content"]) for e in evidence]
        # 合并顺序: 跨流关系反思在前 (泛化原料是身份信念的核心证据),
        # 共享流世界观察在后 (补充情境)。不重复 (世界观察已在 ev_ids)。
        merged = ev_pairs + [x for x in ev_ids
                             if x[0] not in {i for (i, _c) in ev_pairs}]
        if not merged:
            return []
        new_ids: list[int] = []
        for insight, ev_used in self._llm.reflection_insights(merged, n=3):
            new_id = self._writer.save(
                store, now, content=insight, evidence=ev_used, player_id=None,
                confidence=0.8, rtype="identity", shared=True, cross_stream=True)
            if new_id is not None:
                new_ids.append(new_id)
        return new_ids

    def check_conflicts(self, store: ConflictMemory, player_id: str | None,
                        now: float, shared: bool = False) -> list[int]:
        """按当前策略检查单个关系流或共享信念，不改变 NPC 触发水位。"""
        return self._conflicts.check(store, player_id, now, shared,
                                     policy=self.conflict_policy)
