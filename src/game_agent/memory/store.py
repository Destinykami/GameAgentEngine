"""记忆流: SQLite 存储 + 三维检索评分。

数据模型 (每条记忆):
- type:        observation | reflection | plan
- content:     自然语言内容
- timestamp:   游戏内时间 (小时, 单调递增)
- importance:  1-10, 记忆创建时打分 (以玩家为参照系时更高)
- player_id:   关联玩家; None = 世界记忆 / 自我记忆 (共享)
- evidence:    反思的证据记忆 id 列表 (JSON)
- confidence:  反思置信度 0-1
- valid:       反思是否仍有效 (冲突时失效)
- last_accessed: 上次被检索的时间 (用于 recency)
- base_confidence/base_importance: 幂等衰减/冲突衰减的重算基线
- hearsay/hop: 传闻来源 (hop=0 亲见; 检索按 0.8^hop 打折)
- consolidated: 已被情节摘要吸收 (仍 valid 可检索, 退出冲突扫描)
- last_reinforced: 上次 importance 强化时间 (merge 限速锚点)

检索评分 (论文方法, 权重均为 1):
score(m, q) = recency(m) + importance(m) + relevance(m, q)
其中 recency = 0.995 ** Δt (Δt 为距上次被检索的游戏内小时数);
recency 与 relevance 在候选集内 Min-Max 归一化, importance 用**绝对**
importance/10 (不归一化)。这是有意取舍: importance 是 1-10 的绝对显著度
(与论文的候选集内相对排序不同), 保留"绝对重要"语义; recency/relevance
仍是相对排序。若要做论文严格对齐, 单独开评测再改。
"""

from __future__ import annotations

from typing import Any, Iterable, Sequence

from ..models.embeddings import Embedder, cosine_similarity
from .models import MemoryRecord
from .policies import (
    ALPHA_IMPORTANCE, ALPHA_RECENCY, ALPHA_RELEVANCE, FORGET_FLOOR,
    FORGET_HALF_LIVES, HEARSAY_DECAY, HEARSAY_MAX_HOP, MERGE_REINFORCE_INTERVAL,
    MIN_IMPORTANCE, OBS_DEDUP_THRESHOLD, RECENCY_DECAY,
    apply_observation_merge, decay_updates,
)
from .ranking import rank_memories
from .repository import MemoryRepository


class MemoryStore:
    """单个 NPC 的记忆存储 (自我 + 世界 + 各玩家关系流, 同库不同 player_id)。"""

    def __init__(self, embedder: Embedder, path: str = ":memory:") -> None:
        self._embedder = embedder
        self._repository = MemoryRepository(path)
        # 每 Store 独立的非持久化向量缓存；冷启动仍批量补 miss。
        self._vec_cache: dict[int, list[float]] = {}

    # ------------------------------------------------------------------ 写入
    def add(self, rec: MemoryRecord) -> int:
        """写入一条记忆, 返回分配的 id。"""
        with self._repository.insert(rec) as new_id:
            self._vec_cache[new_id] = self._embedder.embed([rec.content])[0]
            return new_id

    # ------------------------------------------------------------------ 读取
    def _vec(self, rec: MemoryRecord) -> list[float]:
        if rec.id is not None and rec.id in self._vec_cache:
            return self._vec_cache[rec.id]
        vec = self._embedder.embed([rec.content])[0]
        if rec.id is not None:
            self._vec_cache[rec.id] = vec
        return vec

    def vectors(self, recs: Sequence[MemoryRecord]) -> list[list[float]]:
        """批量取向量 (F6-8): 只对缓存 miss 的记忆发一次 embed 批量请求。

        RealEmbedder 下从磁盘恢复大世界后, 首波检索若逐条嵌入就是 O(n) 次网络
        请求; 这里把 miss 收集成一批。已入库记忆的向量在 add 时已缓存, 通常全命中。
        """
        return self._ensure_vecs(list(recs))

    def vector(self, rec: MemoryRecord) -> list[float]:
        """取某记忆的向量 (命中缓存则不重嵌入)。供反思去重等需比较既有记忆的
        向量场景使用 (L1): 已入库记忆的向量在 add 时已缓存, 此处零嵌入成本。"""
        return self._vec(rec)

    def _ensure_vecs(self, recs: Sequence[MemoryRecord]) -> list[list[float]]:
        """确保 recs 的向量都在缓存里, 返回与 recs 对齐的向量列表 (批量 miss)。"""
        recs = list(recs)
        missing = [r for r in recs
                   if r.id is None or r.id not in self._vec_cache]
        if missing:
            encoded = self._embedder.embed([r.content for r in missing])
            for rec, vec in zip(missing, encoded):
                if rec.id is not None:
                    self._vec_cache[rec.id] = vec
        out: list[list[float]] = []
        for rec in recs:
            if rec.id is not None and rec.id in self._vec_cache:
                out.append(self._vec_cache[rec.id])
            else:
                out.append(self._embedder.embed([rec.content])[0])
        return out

    def all_valid(self, player_id: str | None = None,
                  types: Sequence[str] | None = None,
                  shared: bool = False,
                  consolidated: bool | None = None,
                  include_shared: bool = False,
                  hearsay_only: bool = False) -> list[MemoryRecord]:
        """取全部有效记忆 (可按玩家/类型过滤), 用于反思与展示。

        E2 语义拆分: `player_id=None` 是"不过滤" (返回所有玩家+共享流, 供衰减/
        计划查询/近期上下文); `shared=True` 是"只取共享流" (player_id IS NULL,
        世界/自我记忆)。二者不再混用 —— 自我反思要的是共享流 (我是谁), 不是
        全玩家关系观察 (谁对我做了什么), 旧实现用 None 拿全玩家流, 自我反思被
        关系观察污染 (E8)。

        E5: `ORDER BY id` —— id 自增即插入序 (= 时间序)。多处用 `[-n:]` 取"最近
        n 条" (find_similar_observation 去重窗口、反思近期观察、世界记忆上下文),
        旧实现无 ORDER BY, 靠 SQLite 恰好按 rowid 返回, 是隐性依赖, 加显式排序。

        include_shared: 与 player_id 联用, 返回该玩家面 + 共享流 (player_id IS
        NULL)。对话检索用它隔离其他玩家的私有记忆; 默认 False 保持旧语义
        (只取该玩家面)。
        """
        return self._repository.all_valid(
            player_id=player_id, types=types, shared=shared,
            consolidated=consolidated, include_shared=include_shared,
            hearsay_only=hearsay_only)


    # ------------------------------------------------------------------ 检索
    def retrieve(self, query: str, now: float,
                 player_id: str | None = None,
                 top_k: int = 8,
                 include_player: str | None = None,
                 min_score: float = 0.0,
                 types: Sequence[str] | None = None,
                 mark_accessed: bool = True,
                 min_relevance: float = 0.0,
                 shared: bool = False,
                 include_shared: bool = False,
                 hearsay_only: bool = False) -> list[dict]:
        """三维检索。

        - query: 查询文本 (应已含玩家身份, 使 relevance 偏向该玩家)。
        - now: 当前游戏内时间。
        - player_id: 限定只检索某玩家的关系流 (可选)。
        - shared: 只检索共享流 (player_id IS NULL, 世界/自我记忆), 同 all_valid
          (E2)。自我反思的证据检索用它, 不把某玩家的关系观察当成自我证据。
        - include_player: 在评分上额外给"属于该玩家"的记忆加权 (千人千面)。
        - include_shared: 与 player_id 联用, 候选集 = 该玩家的面 + 共享流
          (player_id IS NULL)。对话用 True (只让当前对话者的面与共享世界记忆
          进入 prompt, 防止把别的玩家的私有记忆说给当前玩家); 反思证据检索
          保持默认 False (只以该玩家面的观察为证据)。
        - hearsay_only: 只检索传闻记忆 (hearsay=1)。转述路径用它找"与当前
          话题相关"的传闻, 不再无条件取最新一条。
        - types: 限定记忆类型 (如 ["observation"]), 用于让反思只以真实观察为证据,
          切断"反思引用反思"的级联。
        - mark_accessed: 是否把进 top_k 的记忆刷新 last_accessed (遗忘锚点)。
          对话 (NPC 真正拿记忆开口) 用默认 True —— 进 top_k 即"被回忆", 抗遗忘;
          反思证据检索传 False —— 候选证据只是"被考虑", 真正被引用的观察已由
          "被反思引用即保护"单独兜底, 不该把 top_k 里没被引用的也一并续命
          (M7: 反思 10×3 问静默给无关观察续命)。
        - min_relevance: 原始余弦相关性下限, 低于它的候选直接剔除 (归一化前)。
          min-max 归一化会把"小存储里最不差的那条"抬成满分, min_score=0.0 又
          全收, 于是小库必返回满 top_k 含无关记忆; 一个绝对相关性下限挡住这种
          灌水 (M7)。默认 0.0 不过滤, 行为与旧版一致。
        """
        q_vec = self._embedder.embed([query])[0]
        cands = self.all_valid(player_id=player_id, types=types, shared=shared,
                               include_shared=include_shared, hearsay_only=hearsay_only)
        if not cands:
            return []
        relevance = [cosine_similarity(v, q_vec) for v in self._ensure_vecs(cands)]
        ranked = rank_memories(
            cands, relevance, now, top_k=top_k, include_player=include_player,
            min_score=min_score, min_relevance=min_relevance,
            recency_decay=RECENCY_DECAY,
            weights=(ALPHA_RECENCY, ALPHA_IMPORTANCE, ALPHA_RELEVANCE),
            hearsay_decay=HEARSAY_DECAY)
        results = []
        for score, c in ranked:
            # 更新 last_accessed (recency 的语义: 距上次检索的时间); 反思证据检索
            # 传 mark_accessed=False 关闭 —— 候选 ≠ 回忆 (M7)。
            if mark_accessed:
                self._mark_accessed(c.id, now)
            results.append({
                "id": c.id,
                "type": c.type,
                "content": c.content,
                "timestamp": c.timestamp,
                "importance": c.importance,
                "player_id": c.player_id,
                "confidence": c.confidence,
                "evidence": c.evidence,
                "hearsay": c.hearsay,   # S4: 下游 (对话 prompt 等) 可显传闻身份
                "hop": c.hop,
                "score": score,
            })
        return results



    def _mark_accessed(self, mem_id: int, now: float) -> None:
        self._repository.mark_accessed(mem_id, now)

    # ------------------------------------------------------- 反思失效/更新
    def invalidate(self, mem_id: int, reason: str = "") -> None:
        """把某条反思标记为失效 (冲突时)。"""
        self._repository.invalidate(mem_id, reason)
        self._vec_cache.pop(mem_id, None)

    def update_confidence(self, mem_id: int, confidence: float) -> None:
        """更新反思置信度 (证据冲突时衰减)。"""
        self._repository.update_confidence(mem_id, max(0.0, min(1.0, confidence)))

    def _set_importance(self, mem_id: int, importance: float) -> None:
        """设某条记忆的 importance (遗忘降权用; 只降不升, 下限 MIN_IMPORTANCE)。"""
        self._repository.set_importance(mem_id, max(MIN_IMPORTANCE, min(10.0, importance)))

    def count(self, player_id: str | None = None) -> int:
        return self._repository.count(player_id)

    # ------------------------------------------------------------------ 观察去重
    def find_similar_observation(self, content: str,
                                 player_id: str | None = None,
                                 threshold: float = OBS_DEDUP_THRESHOLD,
                                 recent_n: int = 50) -> MemoryRecord | None:
        """在同玩家的近期观察里找语义近义的一条 (>= threshold), 否则 None。

        只在观察层做 (反思去重在 reflection.py), 且限定同一玩家流 ——
        跨玩家"相似"是不同关系, 不该合并。

        L5: 去重窗口只覆盖同玩家最近 recent_n (50) 条。窗口外的重放 (同一事件
        隔了 50+ 条别的观察后再次发生) 会重复入库 —— 轻微灌水, 可接受。不扩大
        窗口: 每次 observe 的去重是 O(窗口) 余弦, 窗口越大每次观察越贵, 而窗口
        外重放是低频边缘情况, 不值得用高频路径的成本去兜。
        """
        cands = self.all_valid(player_id=player_id,
                               types=["observation"])[-recent_n:]
        if not cands:
            return None
        v_new = self._embedder.embed([content])[0]
        cand_vecs = self._ensure_vecs(cands)   # F6-8: 批量补 miss
        best: MemoryRecord | None = None
        best_s = 0.0
        for c, c_vec in zip(cands, cand_vecs):
            s = cosine_similarity(c_vec, v_new)
            if s >= threshold and s > best_s:
                best, best_s = c, s
        return best

    def merge_observation(self, mem_id: int, now: float,
                          new_hearsay: bool | None = None,
                          new_hop: int = 0,
                          new_content: str | None = None) -> float:
        """合并重复观察: 刷新 last_accessed (重复发生 = 被回忆, 抗遗忘),
        并按时间窗 (+1, 上限 10) 强化 importance。

        强化是**固定 +1 的重复计数**, 不加新观察的完整 importance: 事件的重要
        性在首次入库时已计入, 重复合并再加一次全量等于双重计分 (一条重要性 9
        的背叛重复一次就从 5 直接顶满 10)。旧版此函数有个 extra_importance
        参数但函数体硬编码 +1 从不读取 (M6 死参数), 调用方传的值被静默丢弃,
        现已删除。

        F2-1 限速: 世界层每个 step 都会 perceive→observe→merge 同一在场观察,
        若每次 merge 都 +1, 站桩的玩家几步内就把 importance 顶满 10, 真实事件
        反而排到后面。只有距上次强化 >= MERGE_REINFORCE_INTERVAL (6 游戏小时)
        才 +1; 其他 merge 只刷新 last_accessed, importance/base 不动。
        强化时同步抬高 base_importance (E1): 衰减基线必须跟上, 否则
        decay_and_forget 会从旧基线重算、把增益抹掉。返回新 importance。

        F6-10 内容合并: new_content 比旧记录更丰富 (更长) 时替换 content 并清
        向量缓存 —— 否则 compressed 档的"P 在 L"会永久压住 full 档的
        "P 出现在 L, 靠近 NPC", 细节丢失。等长/更短不替换, 避免抖动。

        F4-2 来源合并: new_hearsay 为 None 时不动来源 (直接调用/测试兼容);
        传入 False (亲见) 且旧记录是传闻 → 升级为亲见 (hop=0); 旧记录已是
        亲见则不降级; 两者都是传闻时保留更近的 hop。这样"先听传闻、后亲眼
        见到"不会让亲见被永久按传闻打折。
        """
        with self._repository.edit_observation(mem_id) as rec:
            old_content = rec.content
            apply_observation_merge(
                rec, now, new_hearsay=new_hearsay, new_hop=new_hop,
                new_content=new_content, reinforce_interval=MERGE_REINFORCE_INTERVAL)
            if rec.content != old_content:
                self._vec_cache.pop(mem_id, None)
            return rec.importance

    def mark_consolidated(self, mem_ids: Iterable[int]) -> int:
        """M1 固化标记: 把被情节摘要 (episode) 吸收的原始观察标 consolidated=1。
        记忆仍 valid、仍可检索, 只是退出冲突扫描 (由 episode 顶替"更晚证据"角色)。
        返回标记的条数。"""
        return self._repository.mark_consolidated(mem_ids)

    def all_invalid(self) -> list[MemoryRecord]:
        """取全部已失效记忆 (冲突失效), 按时间排序, 供审查。

        注意: 遗忘改为降权后不再产生失效记录, 这里只剩冲突失效的反思。
        仓储统一读取完整记录，新加字段 (hearsay/hop/consolidated/
        last_reinforced) 不再被截断或默认化。
        """
        return self._repository.all_invalid()

    # ------------------------------------------------------------------ 遗忘
    def decay_and_forget(self, now: float,
                         half_lives: dict[str, float] | None = None
                         ) -> list[int]:
        """时间遗忘 (部分衰减降权, 不删除): 把每条未受保护记忆的 importance
        降到衰减水位, 渐近到 MIN_IMPORTANCE 为止, 返回被降权的 id。

        importance = base_importance * 0.5 ** (age / half_life)  (E1 幂等水位),
          age = now - max(timestamp, last_accessed or timestamp)
                (被回忆过 / merge 刷新的记忆锚点后移、衰减更慢, 抗遗忘)
        base_importance 是衰减的起始基线 (插入时 = 初始 importance, merge 提升
        时同步抬高), **不被衰减本身修改**。每次清扫都从基线重算 —— 重扫不漂移、
        不复合。旧实现是 `m.importance * factor`, 对已被降过的当前值再乘满年龄
        因子, 随清扫次数超线性加速 (6h 节奏 48h 触底), 半衰期语义失效。
        记忆**保留** (valid 恒 1), 只降 importance —— 检索 importance 维随之
        跌出前排, 但仍可被检索。这是"降权"不是"抹除"。
        保护: 被有效反思引用为证据的观察不降权 —— 它已固化为高阶认知,
        降了它会削弱反思的证据链。保护集按当前有效反思快照计算。
        """
        downweighted = []
        for rec, importance in decay_updates(
                self.all_valid(), now, half_lives or FORGET_HALF_LIVES, MIN_IMPORTANCE):
            self._set_importance(rec.id, importance)
            downweighted.append(rec.id)
        return downweighted

    # ------------------------------------------------------------------ 元数据
    def set_meta(self, key: str, value: Any) -> None:
        """存一条 NPC 元数据 (JSON 序列化)。"""
        self._repository.set_meta(key, value)

    def get_meta(self, key: str, default: Any = None) -> Any:
        """取一条 NPC 元数据; 不存在返回 default。"""
        return self._repository.get_meta(key, default)

    def db_path(self) -> str | None:
        """文件库的绝对路径; :memory: 返回 None。"""
        return self._repository.db_path()

    def is_persistent(self) -> bool:
        """是否为文件库 (可持久化); :memory: 返回 False。"""
        return self._repository.is_persistent()

    def close(self) -> None:
        self._repository.close()
