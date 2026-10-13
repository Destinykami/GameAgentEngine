"""反思引擎: 把具体观察提炼为高层认知, 并处理冲突失效。

两类反思:
- 自我反思 (reflect_self): 从世界/自我记忆归纳人物性格、兴趣、动机。
- 关系反思 (reflect_relationship): 从某玩家的关系记忆归纳对该玩家的判断。
  这是"千人千面"的核心 —— 每个玩家各自拥有一份关系反思。

冲突处理 (check_conflicts):
- 若对某玩家已有"信任"类反思, 但之后出现"背叛"类新观察, 则该反思失效/衰减。
- 反过来同理。这保证关系认知能被更新, 而不是一成不变 (持久性探针依赖此)。
"""

from __future__ import annotations

from typing import Sequence

from .embeddings import Embedder, cosine_similarity
from .llm import LLMClient
from .memory import MemoryRecord, MemoryStore

# 反思去重阈值: 新洞察与已有反思语义相似度 >= 0.95 视为同一条认知, 跳过。
# (gte-Qwen2 实测: 措辞不同的重复 0.955~1.000, 不同面向的独立洞察 <= ~0.90)
DEDUP_THRESHOLD = 0.95

# 冲突失效阈值 (LLM 判矛盾强度 0-10): >= 7 直接推翻 → 反思失效; 3-6 部分削弱 → 衰减。
CONFLICT_INVALIDATE = 7
CONFLICT_DECAY = 3

# 冲突检测词表 (启发式, 自包含)。check_conflicts 已升级为 LLM 判矛盾强度,
# 这些词表现仅供离线测试 stub 与语义文档用途, 生产冲突判定不再依赖它们。
TRUST_WORDS = ("信任", "可靠", "朋友", "感激", "亲近", "盟友", "伙伴", "支持者")
DISTRUST_WORDS = ("警惕", "不信任", "不可信", "防备", "背叛", "欺骗", "背叛的轨迹")
HELP_WORDS = ("帮助", "帮", "礼物", "送", "保护", "可靠", "朋友", "信任", "感谢")
HURT_WORDS = ("背叛", "欺骗", "撒谎", "骗", "爽约", "放鸽子", "警惕", "不信任", "不可信", "偷", "伤害")


class ReflectionEngine:
    def __init__(self, llm: LLMClient,
                 embedder: Embedder | None = None,
                 dedup_threshold: float = DEDUP_THRESHOLD) -> None:
        self._llm = llm
        self._embedder = embedder
        self._dedup_threshold = dedup_threshold
        # 冲突判断缓存: (反思内容, 观察内容) → 矛盾强度。反思与观察内容稳定,
        # 重复检查同一对零 LLM 成本 (check_conflicts 可能被多次触发)。
        self._conflict_cache: dict[tuple[str, str], int] = {}

    # ------------------------------------------------------------- 自我反思
    def reflect_self(self, store: MemoryStore, now: float,
                     recent_n: int = 100) -> list[int]:
        """从最近的自我/世界记忆生成自我反思, 返回新记忆 id。"""
        # 只用真实观察生成问题与证据: 若把反思也纳入, 反思会拿别的反思当证据,
        # 一代代复述放大自己 (级联失控)。观察是唯一的"事实"来源。
        recent = store.all_valid(player_id=None, types=["observation"])
        recent = recent[-recent_n:]
        if not recent:
            return []
        texts = [m.content for m in recent]
        questions = self._llm.reflection_questions(texts)

        new_ids: list[int] = []
        for q in questions:
            evidence = store.retrieve(query=q, now=now,
                                      player_id=None, top_k=10,
                                      types=["observation"])
            ev_pairs = [(e["id"], e["content"]) for e in evidence]
            if not ev_pairs:
                continue
            for insight, ev_ids in self._llm.reflection_insights(ev_pairs, n=3):
                new_id = self._save(store, now, content=insight,
                                    evidence=ev_ids, player_id=None,
                                    confidence=0.8)
                if new_id is not None:
                    new_ids.append(new_id)
        return new_ids

    # ------------------------------------------------------------- 关系反思
    def reflect_relationship(self, store: MemoryStore, player_id: str,
                             now: float) -> list[int]:
        """对某玩家的关系记忆生成关系反思, 返回新记忆 id。"""
        rel = store.all_valid(player_id=player_id, types=["observation"])
        if not rel:
            return []
        texts = [m.content for m in rel]
        questions = self._llm.reflection_questions(texts)
        if not questions:
            questions = [f"Klaus 和 {player_id} 的关系如何?"]

        new_ids: list[int] = []
        for q in questions:
            # 证据只用真实观察, 不用其他反思 → 切断"反思引用反思"的级联。
            evidence = store.retrieve(query=q, now=now, player_id=player_id,
                                      top_k=10, include_player=player_id,
                                      types=["observation"])
            ev_pairs = [(e["id"], e["content"]) for e in evidence]
            if not ev_pairs:
                continue
            for insight, ev_ids in self._llm.reflection_insights(ev_pairs, n=3):
                # 关系反思的置信度: 证据越多越高, 但有上限
                confidence = min(0.95, 0.5 + 0.1 * len(ev_ids))
                new_id = self._save(store, now, content=insight,
                                    evidence=ev_ids, player_id=player_id,
                                    confidence=confidence)
                if new_id is not None:
                    new_ids.append(new_id)
        return new_ids

    # ------------------------------------------------------------- 冲突处理
    def check_conflicts(self, store: MemoryStore, player_id: str,
                        now: float) -> list[int]:
        """检测关系反思与更晚观察的矛盾 (LLM 判矛盾强度), 失效/衰减矛盾反思。

        取代词表方向匹配: 让 LLM 判语义矛盾强度 0-10 —— 强背叛推翻强信任 =
        高分 → 失效; 轻微帮助削弱轻微警惕 = 中分 → 衰减。只检查**更晚**的观察
        (时间上只有新证据能推翻旧信念)。判断按 (反思内容, 观察内容) 缓存,
        重复检查同一对零 LLM 成本。

        衰减是**幂等的目标水位** (H1), 不是累加操作:
            目标置信度 = base_confidence * 0.5 ** (不同冲突观察的条数)
        同一组证据重跑 check_conflicts, 水位不变 (守卫拦住重复写入); 一条**新**
        冲突观察让指数 +1, 恰好多折半一次 —— "一条证据削弱一次信念"。旧实现
        是"找到冲突对就乘 0.5 再 break", 缓存只记判定不记效果, 每跑一遍再折半,
        对话越多置信度塌得越快 (0.8→0.4→0.2→...)。
        """
        handled: list[int] = []
        reflections = store.all_valid(player_id=player_id, types=["reflection"])
        observations = store.all_valid(player_id=player_id, types=["observation"])

        for ref in reflections:
            decay_count = 0
            invalidated = False
            for obs in observations:
                if obs.timestamp <= ref.timestamp:
                    continue   # 只有更晚的观察能矛盾更早的反思
                key = (ref.content, obs.content)
                cached = self._conflict_cache.get(key)
                if cached is not None:
                    severity = cached
                else:
                    severity = self._llm.judge_conflict(ref.content, obs.content)
                    self._conflict_cache[key] = severity
                if severity >= CONFLICT_INVALIDATE:
                    store.invalidate(ref.id)   # 强烈矛盾 → 直接推翻, 反思失效
                    invalidated = True
                    break
                if severity >= CONFLICT_DECAY:
                    decay_count += 1           # 数全部部分矛盾, 不 break
            if invalidated:
                handled.append(ref.id)
            elif decay_count:
                target = ref.base_confidence * (0.5 ** decay_count)
                if target < ref.confidence - 1e-9:   # 只写实际下降, 重跑不重复写
                    store.update_confidence(ref.id, target)
                    handled.append(ref.id)
        return handled

    # --------------------------------------------------------------- 内部
    def _save(self, store: MemoryStore, now: float, content: str,
              evidence: Sequence[int], player_id: str | None,
              confidence: float) -> int | None:
        """保存反思; 与同玩家已有反思几乎同义 (>= 阈值) 时跳过, 返回 None。"""
        if self._embedder is not None and self._dedup_threshold > 0:
            existing = store.all_valid(player_id=player_id, types=["reflection"])
            if existing:
                v_new = self._embedder.embed([content])[0]
                v_ex = self._embedder.embed([m.content for m in existing])
                if max(cosine_similarity(v_new, v) for v in v_ex) >= self._dedup_threshold:
                    return None   # 同一条认知的又一次复述, 不入库
        rec = MemoryRecord(
            content=content, timestamp=now, type="reflection",
            player_id=player_id, evidence=list(evidence),
            confidence=confidence, base_confidence=confidence, valid=True,
        )
        return store.add(rec)
