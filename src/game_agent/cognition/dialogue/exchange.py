"""两个回复端口轮流发言；不接管 NPC 的观察记录或反思触发。"""

from __future__ import annotations

from .contracts import DialogueSpeaker


def two_agent_exchange(self_a: DialogueSpeaker, name_a: str,
                       self_b: DialogueSpeaker, name_b: str,
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
