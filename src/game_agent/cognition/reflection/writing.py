"""反思写入规则：同流同类型去重、证据校验及记忆记录构造。"""

from __future__ import annotations

from typing import Sequence

from ...memory.models import MemoryRecord
from ...models.embeddings import Embedder, cosine_similarity
from .contracts import ReflectionWriteMemory
from .policies import DEDUP_THRESHOLD


class ReflectionWriter:
    def __init__(self, embedder: Embedder | None = None,
                 dedup_threshold: float = DEDUP_THRESHOLD) -> None:
        self._embedder = embedder
        self._dedup_threshold = dedup_threshold

    def save(self, store: ReflectionWriteMemory, now: float, content: str,
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
