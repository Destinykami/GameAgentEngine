"""信念冲突处理与实例独有的 LRU 判断缓存。"""

from __future__ import annotations

from collections import OrderedDict

from .contracts import ConflictJudge, ConflictMemory
from .policies import (
    CONFLICT_CACHE_LIMIT, CONFLICT_DECAY, CONFLICT_DECAY_FLOOR,
    CONFLICT_INVALIDATE, CONFLICT_RECENT_OBS, DISTRUST_WORDS, TRUST_WORDS,
)


class ConflictResolver:
    def __init__(self, llm: ConflictJudge) -> None:
        self._llm = llm
        self._cache: OrderedDict[tuple[str, str], int] = OrderedDict()

    def check(self, store: ConflictMemory, player_id: str | None,
              now: float, shared: bool = False, *,
              policy: str = "full") -> list[int]:
        """冲突处理入口: 按 policy 分派 (消融开关, 缺省 full = 现行为)。

        shared=True 时检查共享流的自我反思 + identity 信念 (player_id 仍用于
        日志/接口兼容, 实际按 shared=True 取流)。关系反思的冲突检查仍走
        player_id 路径 (shared=False)。
        """
        if policy == "off":
            return []
        if policy == "heuristic_decay":
            return self._check_heuristic(store, player_id, now, shared)
        return self._check_llm(store, player_id, now, shared)

    def _check_llm(self, store: ConflictMemory, player_id: str | None,
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
                cached = self._cache.get(key)
                if cached is not None:
                    self._cache.move_to_end(key)
                    severity = cached
                else:
                    severity = self._llm.judge_conflict(ref.content, obs.content)
                    self._cache[key] = severity
                    while len(self._cache) > CONFLICT_CACHE_LIMIT:
                        self._cache.popitem(last=False)
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

    def _check_heuristic(self, store: ConflictMemory, player_id: str | None,
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
