"""真实 LLM 的组装入口；任务、解析、传输和统计分别负责各自规则。"""

from __future__ import annotations

from typing import Any, Sequence

from ..llm import LLMClient, LLMContext
from ..config import (DEFAULT_LLM_BASE_URL as DEFAULT_BASE_URL,
                      DEFAULT_LLM_MODEL as DEFAULT_MODEL, EndpointConfig)
from . import actions, dialogue, game, memory, planning
from .parsing import request_json
from .transport import request_chat
from .usage import new_stats, record_stats


class RealLLM(LLMClient):
    def __init__(self, base_url: str = DEFAULT_BASE_URL,
                 model: str = DEFAULT_MODEL, api_key: str = "",
                 enable_thinking: bool = False,
                 timeout: float = 60.0, max_retries: int = 2) -> None:
        self.endpoint = EndpointConfig(base_url.rstrip("/"), model, api_key,
                                       timeout, max_retries)
        self.enable_thinking = enable_thinking
        self.stats = new_stats()

    def reset_stats(self) -> None:
        self.stats = new_stats()

    def _record_stats(self, tag: str, latency_s: float, usage: dict) -> None:
        record_stats(self.stats, tag, latency_s, usage)

    def _chat(self, system: str, user: str, *, think: bool = False,
              temperature: float = 0.0, max_tokens: int = 512,
              _stats_tag: str = "unspecified") -> str:
        return request_chat(self.endpoint, self._record_stats, system, user,
                            think=think, temperature=temperature,
                            max_tokens=max_tokens, _stats_tag=_stats_tag)

    def _chat_json(self, system: str, user: str, *, think: bool = False,
                   temperature: float = 0.0, max_tokens: int = 2048,
                   _stats_tag: str = "unspecified") -> Any:
        return request_json(self._chat, system, user, think=think,
                            temperature=temperature, max_tokens=max_tokens,
                            _stats_tag=_stats_tag)

    def ask(self, question: str, system: str = "", *, think: bool = False,
            temperature: float = 0.0, max_tokens: int = 256) -> str:
        """公开的单轮问答 (供探针裁判、外部逻辑复用)。默认关思考、低温。"""
        return self._chat(system or "你是一个简洁的助手。", question,
                          think=think, temperature=temperature,
                          max_tokens=max_tokens, _stats_tag="ask")

    def complete(self, ctx: LLMContext) -> str:
        return dialogue.complete(self._chat, ctx, thinking=self.enable_thinking)

    def perceive_action(self, npc_name: str, player_name: str, action: str,
                        context: str = "") -> str:
        return dialogue.perceive_action(self._chat, npc_name, player_name, action, context)

    def score_importance(self, text: str, player_id: str | None = None) -> float:
        return memory.score_importance(self._chat, text, player_id)

    def reflection_questions(self, recent: Sequence[str]) -> list[str]:
        return memory.reflection_questions(self._chat_json, recent)

    def reflection_insights(self, evidence: list[tuple[int, str]],
                            n: int = 5) -> list[tuple[str, list[int]]]:
        return memory.reflection_insights(self._chat_json, evidence, n)

    def judge_trust(self, memories: list[tuple[str, str, float]],
                    player_id: str) -> float:
        return memory.judge_trust(self._chat, memories, player_id)

    def judge_conflict(self, reflection: str, observation: str) -> int:
        return memory.judge_conflict(self._chat, reflection, observation)

    def consolidate_observations(self, observations: Sequence[str],
                                 player_id: str | None = None) -> str:
        return memory.consolidate_observations(self._chat, observations, player_id)

    def generate_plan(self, persona_traits: dict[str, float],
                      previous_day: str, date: str,
                      context: str = "") -> list[tuple[int, int, str]]:
        return planning.generate_plan(self._chat_json, persona_traits, previous_day,
                                      date, context)

    def decompose_activity(self, activity: str, start: int, end: int) -> \
            list[tuple[int, int, str]]:
        return planning.decompose_activity(self._chat_json, activity, start, end)

    def decide_action(self, agent_name: str, goal: str,
                      persona_traits: dict[str, float], perception: str,
                      history: list[str], state: str) -> dict:
        return actions.decide_action(self._chat_json, agent_name, goal, persona_traits,
                                     perception, history, state)

    def decide_game(self, context):
        """可选的新能力，旧 LLMClient 实现无需增加抽象方法。"""
        return game.decide_game(self._chat_json, context)

    def score_event(self, event: str, persona_traits: dict[str, float],
                    current_plan: str = "") -> tuple[float, float, float]:
        return actions.score_event(self._chat_json, event, persona_traits, current_plan)
