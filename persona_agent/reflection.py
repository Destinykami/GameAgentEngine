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

from .llm import LLMClient
from .memory import MemoryRecord, MemoryStore

# 冲突检测词表 (启发式, 自包含): 反思里出现信任/警惕类词, 观察里出现帮助/伤害类词。
TRUST_WORDS = ("信任", "可靠", "朋友", "感激", "亲近", "盟友", "伙伴", "支持者")
DISTRUST_WORDS = ("警惕", "不信任", "不可信", "防备", "背叛", "欺骗", "背叛的轨迹")
HELP_WORDS = ("帮助", "帮", "礼物", "送", "保护", "可靠", "朋友", "信任", "感谢")
HURT_WORDS = ("背叛", "欺骗", "撒谎", "骗", "爽约", "放鸽子", "警惕", "不信任", "不可信", "偷", "伤害")


class ReflectionEngine:
    def __init__(self, llm: LLMClient) -> None:
        self._llm = llm

    # ------------------------------------------------------------- 自我反思
    def reflect_self(self, store: MemoryStore, now: float,
                     recent_n: int = 100) -> list[int]:
        """从最近的自我/世界记忆生成自我反思, 返回新记忆 id。"""
        recent = store.all_valid(player_id=None, types=["observation", "reflection"])
        recent = recent[-recent_n:]
        if not recent:
            return []
        texts = [m.content for m in recent]
        questions = self._llm.reflection_questions(texts)

        new_ids: list[int] = []
        for q in questions:
            evidence = store.retrieve(query=q, now=now,
                                      player_id=None, top_k=10)
            ev_pairs = [(e["id"], e["content"]) for e in evidence]
            if not ev_pairs:
                continue
            for insight, ev_ids in self._llm.reflection_insights(ev_pairs, n=3):
                new_ids.append(self._save(store, now, content=insight,
                                          evidence=ev_ids, player_id=None,
                                          confidence=0.8))
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
            evidence = store.retrieve(query=q, now=now, player_id=player_id,
                                      top_k=10, include_player=player_id)
            ev_pairs = [(e["id"], e["content"]) for e in evidence]
            if not ev_pairs:
                continue
            for insight, ev_ids in self._llm.reflection_insights(ev_pairs, n=3):
                # 关系反思的置信度: 证据越多越高, 但有上限
                confidence = min(0.95, 0.5 + 0.1 * len(ev_ids))
                new_ids.append(self._save(store, now, content=insight,
                                          evidence=ev_ids, player_id=player_id,
                                          confidence=confidence))
        return new_ids

    # ------------------------------------------------------------- 冲突处理
    def check_conflicts(self, store: MemoryStore, player_id: str,
                        now: float) -> list[int]:
        """检测关系反思与新观察的冲突, 失效/衰减矛盾的旧反思, 返回被处理的 id。"""
        handled: list[int] = []
        reflections = store.all_valid(player_id=player_id, types=["reflection"])
        observations = store.all_valid(player_id=player_id, types=["observation"])

        for ref in reflections:
            ref_trust = any(w in ref.content for w in TRUST_WORDS)
            ref_distrust = any(w in ref.content for w in DISTRUST_WORDS)
            # 找晚于该反思的观察
            later_obs = [o for o in observations if o.timestamp > ref.timestamp]
            for obs in later_obs:
                obs_trust = any(w in obs.content for w in HELP_WORDS)
                obs_distrust = any(w in obs.content for w in HURT_WORDS)
                if ref_trust and obs_distrust:
                    store.invalidate(ref.id)   # 曾信任, 但新观察是背叛 → 失效
                    handled.append(ref.id)
                    break
                if ref_distrust and obs_trust:
                    # 曾警惕, 但新观察是帮助 → 衰减置信度 (不完全失效)
                    store.update_confidence(ref.id, ref.confidence * 0.5)
                    handled.append(ref.id)
                    break
        return handled

    # --------------------------------------------------------------- 内部
    @staticmethod
    def _save(store: MemoryStore, now: float, content: str,
              evidence: Sequence[int], player_id: str | None,
              confidence: float) -> int:
        rec = MemoryRecord(
            content=content, timestamp=now, type="reflection",
            player_id=player_id, evidence=list(evidence),
            confidence=confidence, valid=True,
        )
        return store.add(rec)
