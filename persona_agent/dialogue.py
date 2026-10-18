"""对话生成: 非全知原则下的逐轮发言。

关键设计 (非全知 / Non-omniscient):
- NPC 只基于自己记忆流里检索到的内容发言, 检索时把"当前对话者是谁"作为
  查询的一部分, 并对属于该玩家的记忆加权 (千人千面)。
- 因此同一个问题问不同 NPC, 或因对话者不同而检索到不同的记忆, 回答就会不同。
- LLM 严格只使用检索出的记忆 —— 没有检索到就回答"没印象", 不编造。
"""

from __future__ import annotations

from .llm import LLMClient, LLMContext
from .memory import MemoryStore

# 对话检索的相关性下限 (M7): 原始余弦低于此值的记忆不进 prompt。min-max 归一化 +
# min_score=0.0 会让小存储必返回满 top_k 含无关记忆, 无关记忆塞进 prompt 既费
# token 又诱导 LLM 拿不相干的事作答。0.1 是保守值 —— 只挡"零词面/零语义重叠"的
# 记忆, 不误伤弱相关。
RELEVANCE_FLOOR = 0.1


class DialogueManager:
    def __init__(self, llm: LLMClient, store: MemoryStore,
                 persona_traits: dict[str, float], name: str) -> None:
        self._llm = llm
        self._store = store
        self._traits = persona_traits
        self._name = name   # NPC 自称

    def reply(self, player_id: str, utterance: str, now: float,
              top_k: int = 8) -> str:
        """对玩家的一句发言作出回应。"""
        # 查询 = 玩家话语 + 玩家身份, 使 relevance 偏向与该玩家相关的记忆
        query = f"{utterance} (对话者: {player_id})"
        # 对话 = 真回忆: mark_accessed 保持默认 True (进 top_k 即刷新遗忘锚点);
        # min_relevance 挡掉零重叠的无关记忆 (M7)。候选集限定"当前对话者的面 +
        # 共享流": 别的玩家的私有记忆不得进入本轮 prompt (面隔离/防秘密泄漏)。
        memories = self._store.retrieve(
            query=query, now=now, top_k=top_k, player_id=player_id,
            include_player=player_id, include_shared=True,
            min_relevance=RELEVANCE_FLOOR)
        # 记忆流是第三人称叙述, 必须显式告诉模型: 记忆里的名字就是你自己,
        # 开口时改用"我", 否则模型会把 NPC 自己当成第三方复述 (自指 bug)。
        ctx = LLMContext(
            system=(f"你是 {self._name}。记忆流里出现的 {self._name} 就是你本人, "
                    f"开口时一律用'我', 不要在自己的话里用名字称呼自己。"
                    f"只基于你记得的事情回答。人格特质: {self._traits}"),
            player_id=player_id,
            memories=memories,
            question=utterance,
        )
        return self._llm.complete(ctx)

    # ------------------------------------------------- 两名 NPC 互相对话
    @staticmethod
    def two_agent_exchange(self_a: "DialogueManager", name_a: str,
                           self_b: "DialogueManager", name_b: str,
                           opener: str, now: float,
                           rounds: int = 2) -> list[dict]:
        """两个 NPC 轮流发言, 各自只用自己的记忆流 (非全知)。"""
        transcript: list[dict] = []
        utterance = opener
        speaker_a = True
        for _ in range(rounds * 2):
            if speaker_a:
                reply = self_a.reply(player_id=name_b, utterance=utterance, now=now)
                transcript.append({"speaker": name_a, "utterance": reply})
            else:
                reply = self_b.reply(player_id=name_a, utterance=utterance, now=now)
                transcript.append({"speaker": name_b, "utterance": reply})
            utterance = reply
            speaker_a = not speaker_a
        return transcript
