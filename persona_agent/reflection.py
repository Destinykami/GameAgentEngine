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

# 冲突检测的成本封顶 (M2): 每对 反思×观察 都是一次 LLM 调用, 全量配对是
# O(反思×观察), 长关系流首跑/重启即数百次尖峰。两端各砍一刀:
# - CONFLICT_RECENT_OBS: 每个反思只查**最近 K 条更晚观察**。一条观察能推翻反思
#   只可能发生在它还是新证据时 (那时在窗口内); 老到窗口外, 反思要么早被它失效,
#   要么生成时已把它算进证据。首跑成本压到 O(反思×K)。
# - CONFLICT_DECAY_FLOOR: 置信度跌破地板的反思直接跳过 —— 检索权重已被
#   confidence 乘到近乎 0, 功能上已死, 再为它判矛盾是浪费; 被部分矛盾的反思
#   陆续跌破地板退出活跃集, 每条新观察的配对成本随衰减递减。
CONFLICT_RECENT_OBS = 10
CONFLICT_DECAY_FLOOR = 0.1

# 冲突检测词表 (启发式, 自包含)。check_conflicts 已升级为 LLM 判矛盾强度,
# 这些词表现仅供离线测试 stub 与语义文档用途, 生产冲突判定不再依赖它们。
TRUST_WORDS = ("信任", "可靠", "朋友", "感激", "亲近", "盟友", "伙伴", "支持者")
DISTRUST_WORDS = ("警惕", "不信任", "不可信", "防备", "背叛", "欺骗", "背叛的轨迹")
HELP_WORDS = ("帮助", "帮", "礼物", "送", "保护", "可靠", "朋友", "信任", "感谢")
HURT_WORDS = ("背叛", "欺骗", "撒谎", "骗", "爽约", "放鸽子", "警惕", "不信任", "不可信", "偷", "伤害")


class ReflectionEngine:
    def __init__(self, llm: LLMClient,
                 embedder: Embedder | None = None,
                 dedup_threshold: float = DEDUP_THRESHOLD,
                 npc_name: str = "") -> None:
        self._llm = llm
        self._embedder = embedder
        self._dedup_threshold = dedup_threshold
        # 本引擎所属 NPC 的名字 (关系反思兜底问题需要; 无名时退中性 "NPC",
        # 不写死任何 demo 名字)。
        self._npc_name = npc_name
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
            # mark_accessed=False: 证据检索只是"考虑候选", 不是"被回忆" —— 刷新
            # 遗忘锚点会让反思静默给 top_k 里没被引用的观察续命 (M7)。真正被引用
            # 为证据的观察由"被有效反思引用即保护"单独兜底, 不依赖此副作用。
            evidence = store.retrieve(query=q, now=now,
                                      player_id=None, top_k=10,
                                      types=["observation"],
                                      mark_accessed=False)
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
                                      types=["observation"],
                                      mark_accessed=False)
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

        成本封顶 (M2): 只对**最近 CONFLICT_RECENT_OBS 条更晚观察**判矛盾, 且
        置信度低于 CONFLICT_DECAY_FLOOR 的反思整个跳过 (功能上已死, 不值得调用)。
        K 窗口同时给衰减一个自然地板: decay_count ≤ K, 信念最低到
        base × 0.5^K 不再被无限磨零。首跑/重启成本从 O(反思×观察) 压到 O(反思×K)。
        """
        handled: list[int] = []
        reflections = store.all_valid(player_id=player_id, types=["reflection"])
        observations = store.all_valid(player_id=player_id, types=["observation"])

        for ref in reflections:
            if ref.confidence < CONFLICT_DECAY_FLOOR:
                continue   # M2: 已死信念不再花 LLM 调用 (衰减/失效都跳过)
            # 只有更晚的观察能矛盾更早的反思; 只取最近 K 条 (M2 成本封顶)。
            # 按时间戳显式排序取最近 K 条 —— 不依赖 all_valid 的插入序, 乱序
            # 写入 (DB 恢复/补记) 也不会取错窗口。
            later = sorted((o for o in observations if o.timestamp > ref.timestamp),
                           key=lambda o: o.timestamp)[-CONFLICT_RECENT_OBS:]
            decay_count = 0
            invalidated = False
            for obs in later:
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
