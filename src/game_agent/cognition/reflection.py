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

from collections import OrderedDict
from typing import Sequence

from ..models.embeddings import Embedder, cosine_similarity
from ..models.llm import LLMClient
from ..memory.store import MemoryRecord, MemoryStore

# 反思去重阈值: 新洞察与已有反思语义相似度 >= 0.92 视为同一条认知, 跳过。
# E6: 原 0.95 取自窄样本实测 (重复 0.955~1.000), 但真实数据 (gte-Qwen2, 1128 对
# 反思两两相似度) 显示"措辞不同的同义复述"稳定落 0.85~0.94, >=0.95 仅 0.1% ——
# 阈值卡在重复带上方, 几乎不生效 (9 条观察产出 48 条反思)。降到 0.92: 抓得住
# 明显近重复 (那几条"旅行者藏眼"变体), 误并独立洞察的风险可控 (独立洞察多 <=0.90,
# 0.90~0.92 的重叠区是已知取舍 —— 宁可少误并, 不追求把 0.85~0.90 的灰区也吃掉)。
DEDUP_THRESHOLD = 0.92

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
CONFLICT_CACHE_LIMIT = 512   # F6-2: (反思, 观察) 判定缓存上限

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
                 npc_name: str = "",
                 evidence_types: tuple[str, ...] = ("observation",),
                 conflict_policy: str = "full",
                 evidence_min_relevance: float = 0.0) -> None:
        self._llm = llm
        self._embedder = embedder
        self._dedup_threshold = dedup_threshold
        # 证据检索类型限定 (消融开关, 缺省 = 现行为):
        # ("observation",) = 级联切断, 反思只引用观察;
        # ("observation", "reflection") = Generative Agents 原始反思 (消融臂)。
        self._evidence_types = tuple(evidence_types)
        # 冲突处理策略 (消融开关, 缺省 "full" = 现行为):
        #   "full"            LLM 判矛盾强度, >=7 失效 / 3-6 衰减
        #   "heuristic_decay" 关键词方向矛盾, 只衰减不失效, 零 LLM (旧词表机制)
        #   "off"             不处理矛盾 (消融基线)
        self._conflict_policy = conflict_policy
        # 反思证据检索的原始相关性下限 (候选证据限制, 缺省 0.0 = 不过滤)
        self._evidence_min_relevance = evidence_min_relevance
        # 本引擎所属 NPC 的名字 (关系反思兜底问题需要; 无名时退中性 "NPC",
        # 不写死任何 demo 名字)。
        self._npc_name = npc_name
        # 冲突判断缓存: (反思内容, 观察内容) → 矛盾强度。反思与观察内容稳定,
        # 重复检查同一对零 LLM 成本 (check_conflicts 可能被多次触发)。
        self._conflict_cache: OrderedDict[tuple[str, str], int] = OrderedDict()

    # ------------------------------------------------------------- 自我反思
    def reflect_self(self, store: MemoryStore, now: float,
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
                                      types=list(self._evidence_types),
                                      min_relevance=self._evidence_min_relevance,
                                      mark_accessed=False)
            ev_pairs = [(e["id"], e["content"]) for e in evidence]
            if not ev_pairs:
                continue
            for insight, ev_ids in self._llm.reflection_insights(ev_pairs, n=3):
                new_id = self._save(store, now, content=insight,
                                    evidence=ev_ids, player_id=None,
                                    confidence=0.8, shared=True)
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
                                      types=list(self._evidence_types),
                                      min_relevance=self._evidence_min_relevance,
                                      mark_accessed=False)
            ev_pairs = [(e["id"], e["content"]) for e in evidence]
            if not ev_pairs:
                continue
            for insight, ev_ids in self._llm.reflection_insights(ev_pairs, n=3):
                # 关系反思的置信度: 证据越多越高, 但有上限
                confidence = min(0.95, 0.5 + 0.1 * len(ev_ids))
                new_id = self._save(store, now, content=insight,
                                    evidence=ev_ids, player_id=player_id,
                                    confidence=confidence, shared=False)
                if new_id is not None:
                    new_ids.append(new_id)
        return new_ids

    # ------------------------------------------------------------- 身份层信念
    def reflect_identity(self, store: MemoryStore, now: float,
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
                                  min_relevance=self._evidence_min_relevance,
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
            new_id = self._save(store, now, content=insight,
                                evidence=ev_used, player_id=None,
                                confidence=0.8, rtype="identity", shared=True,
                                cross_stream=True)
            if new_id is not None:
                new_ids.append(new_id)
        return new_ids

    # ------------------------------------------------------------- 冲突处理
    def check_conflicts(self, store: MemoryStore, player_id: str,
                        now: float, shared: bool = False) -> list[int]:
        """冲突处理入口: 按 _conflict_policy 分派 (消融开关, 缺省 full = 现行为)。

        shared=True 时检查共享流的自我反思 + identity 信念 (player_id 仍用于
        日志/接口兼容, 实际按 shared=True 取流)。关系反思的冲突检查仍走
        player_id 路径 (shared=False)。
        """
        if self._conflict_policy == "off":
            return []
        if self._conflict_policy == "heuristic_decay":
            return self._check_conflicts_heuristic(store, player_id, now, shared)
        return self._check_conflicts_llm(store, player_id, now, shared)

    def _check_conflicts_llm(self, store: MemoryStore, player_id: str,
                             now: float, shared: bool = False) -> list[int]:
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
        if shared:
            # 共享流的自我反思 + identity 信念都参与冲突扫描。identity 是
            # 跨玩家泛化的高阶信念, 同样可能被后续世界观察推翻。
            reflections = (store.all_valid(shared=True, types=["reflection"])
                           + store.all_valid(shared=True, types=["identity"]))
            observations = (
                store.all_valid(shared=True, types=["observation"],
                                consolidated=False)
                + store.all_valid(shared=True, types=["episode"]))
        else:
            reflections = store.all_valid(player_id=player_id,
                                          types=["reflection"])
            # M1 固化后: 已固化的原始观察退出扫描 (被情节摘要吸收, 再由 episode
            # 顶替"更晚证据"角色) —— 一条 episode 顶 N 条观察, 冲突检查从
            # O(反思×观察) 降为 O(反思×(情节+未固化观察))。
            observations = (
                store.all_valid(player_id=player_id, types=["observation"],
                                consolidated=False)
                + store.all_valid(player_id=player_id, types=["episode"]))

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
                    self._conflict_cache.move_to_end(key)
                    severity = cached
                else:
                    severity = self._llm.judge_conflict(ref.content, obs.content)
                    self._conflict_cache[key] = severity
                    while len(self._conflict_cache) > CONFLICT_CACHE_LIMIT:
                        self._conflict_cache.popitem(last=False)
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

    def _check_conflicts_heuristic(self, store: MemoryStore, player_id: str,
                                   now: float, shared: bool = False) -> list[int]:
        """关键词方向矛盾的置信度衰减 (只衰减不失效, 零 LLM 调用)。

        旧词表机制的消融臂: 反思与更晚观察的信任方向相反 (TRUST_WORDS vs
        DISTRUST_WORDS) 即计一次部分矛盾。衰减是幂等目标水位 (同 LLM 路径, H1):
        目标 = base_confidence * 0.5 ** 矛盾观察条数, 重跑不复合。不失效 ——
        本臂隔离"衰减机制本身"与"LLM 判别"。
        """
        handled: list[int] = []
        if shared:
            reflections = (store.all_valid(shared=True, types=["reflection"])
                           + store.all_valid(shared=True, types=["identity"]))
            observations = (
                store.all_valid(shared=True, types=["observation"],
                                consolidated=False)
                + store.all_valid(shared=True, types=["episode"]))
        else:
            reflections = store.all_valid(player_id=player_id,
                                          types=["reflection"])
            # 同 LLM 路径: 已固化观察退出扫描, episode 顶替 (M1)
            observations = (
                store.all_valid(player_id=player_id, types=["observation"],
                                consolidated=False)
                + store.all_valid(player_id=player_id, types=["episode"]))
        for ref in reflections:
            if ref.confidence < CONFLICT_DECAY_FLOOR:
                continue   # 已死信念不值得关键词扫描
            n_conf = 0
            for obs in observations:
                if obs.timestamp <= ref.timestamp:
                    continue   # 只有更晚的观察能削弱旧信念
                ref_trust = any(w in ref.content for w in TRUST_WORDS)
                ref_distrust = any(w in ref.content for w in DISTRUST_WORDS)
                obs_distrust = any(w in obs.content for w in DISTRUST_WORDS)
                obs_trust = any(w in obs.content for w in TRUST_WORDS)
                if (ref_trust and obs_distrust) or (ref_distrust and obs_trust):
                    n_conf += 1
            if n_conf:
                target = ref.base_confidence * (0.5 ** n_conf)
                if target < ref.confidence - 1e-9:   # 只写实际下降, 重跑不重复衰减
                    store.update_confidence(ref.id, target)
                    handled.append(ref.id)
        return handled

    # --------------------------------------------------------------- 内部
    def _save(self, store: MemoryStore, now: float, content: str,
              evidence: Sequence[int], player_id: str | None,
              confidence: float,
              rtype: str = "reflection",
              shared: bool | None = None,
              cross_stream: bool = False) -> int | None:
        """保存反思; 与同流已有反思几乎同义 (>= 阈值) 时跳过, 返回 None。

        rtype: 记忆类型 (缺省 reflection; 身份信念传 "identity", 与常规反思
        分池去重, 也避免身份信念被当成关系反思被证据约束链误引)。

        shared: 去重池的流归属。None 时按 `player_id is None` 推断 ——
        **不能**把 None 直接传给 `all_valid(player_id=None)`: 那是"不过滤"
        不是"共享流" (E2 陷阱), 会让自我反思与所有玩家的关系反思互相去重。

        cross_stream: identity 信念的证据刻意跨流 (关系反思是泛化原料), 校验
        证据 id 时放宽到全部有效记忆; 普通自我/关系反思仍严格同流。
        """
        if shared is None:
            shared = player_id is None
        if self._embedder is not None and self._dedup_threshold > 0:
            if shared:
                existing = store.all_valid(shared=True, types=[rtype])
            else:
                existing = store.all_valid(player_id=player_id, types=[rtype])
            if existing:
                v_new = self._embedder.embed([content])[0]   # 新洞察嵌入一次 (不可避免)
                # L1: 已有反思取 store 缓存向量 (add 时已嵌入缓存), 不再整批重嵌入 ——
                # RealEmbedder (无自缓存) 下每存一条反思的 O(n) 网络嵌入降为 O(1)。
                v_ex = store.vectors(existing)   # F6-8: 批量取已有反思向量
                if max(cosine_similarity(v_new, v) for v in v_ex) >= self._dedup_threshold:
                    return None   # 同一条认知的又一次复述, 不入库
        # F6-3: 引擎层二次校验证据 id —— 只保留同流、仍有效、真实存在的记忆。
        # RealLLM.reflection_insights 已过滤一次, 但 stub/自定义 LLM 会绕过它,
        # 幻影/跨玩家/失效 id 会污染证据链与遗忘保护集。
        if evidence:
            if cross_stream:
                allowed = {m.id for m in store.all_valid()}
            else:
                allowed = {m.id for m in store.all_valid(
                    shared=shared, player_id=player_id)}
            evidence = [i for i in evidence if i in allowed]
        rec = MemoryRecord(
            content=content, timestamp=now, type=rtype,
            player_id=player_id, evidence=list(evidence),
            confidence=confidence, base_confidence=confidence, valid=True,
        )
        return store.add(rec)
