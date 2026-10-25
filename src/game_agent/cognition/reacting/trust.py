"""单关系流取证、信任判断与实例独有的签名缓存。"""

from __future__ import annotations

from .contracts import RelationshipMemory, TrustModel

# 高阶认知最多 10 条，观察最多 20 条；不相互补齐空位。
JUDGE_TRUST_MAX_MEMORIES = 30


class RelationshipTrust:
    def __init__(self, store: RelationshipMemory, llm: TrustModel) -> None:
        self._store = store
        self._llm = llm
        self._cache: dict[str, tuple[float, tuple]] = {}

    @property
    def cache_size(self) -> int:
        return len(self._cache)

    def get(self, player_id: str | None) -> float:
        """对该玩家的信任度 -1..1, 由 LLM 基于关系记忆**内容**判断 (签名缓存)。

        取代关键词词表计数: LLM 能理解"搭把手"=帮、"放鸽子"=背叛等花样措辞。
        信任是**持久的关系认知**: 判断只看关系记忆的内容 (帮过/背叛过),
        刻意**不看 importance** —— 遗忘只降权不删除, 久远的帮助/背叛仍是
        认知, 不会因"久远"而清零。故信任度不随遗忘淡化。
        每次查询关系流，比较实际有序模型证据；命中只省模型调用。
        内容、来源或置信度改变触发重判；importance 和访问时间不参与签名。

        E2: player_id=None 是"无玩家" (世界事件, 如火灾), 不存在"对 None 的信任
        度" —— 旧实现 all_valid(None) 拿全玩家流, 把不同玩家的关系记忆合在一起
        判出一个伪信任度还写进缓存。直接返回中性 0.0。
        """
        if player_id is None:
            return 0.0
        rel = self._store.all_valid(player_id=player_id)
        if not rel:
            return 0.0
        # 高阶最多 10 条、观察最多 20 条，不借用另一池的空位；
        # 只比较实际输入，窗口外及未使用类型的变化不重判。
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
        sig = tuple(mems)
        cached = self._cache.get(player_id)
        if cached is not None and cached[1] == sig:
            return cached[0]
        trust = self._llm.judge_trust(mems, player_id)
        self._cache[player_id] = (trust, sig)
        return trust

    def clear_cache(self) -> None:
        self._cache.clear()
