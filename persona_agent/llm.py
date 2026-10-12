"""LLM 层: LLMClient 抽象接口 + LLMContext 上下文。

框架让 LLM 承担七类推理, 全部抽象成接口方法:
- complete(ctx)                       对话/反应回复
- score_importance(text, player_id)   记忆重要性打分 (1-10)
- reflection_questions(recent)        生成反思用的 3 个高层问题
- reflection_insights(evidence, n)    从证据生成带引用的 Insight
- generate_plan(...)                  生成日计划
- decompose_activity(...)             把活动分解为子任务
- score_event(...)                    判断事件价值 (社交/目标/打断代价)

实现: persona_agent.llm_real.RealLLM (OpenAI 兼容, SGLang 部署)。
实现者只应使用传入的记忆内容 —— 这是"非全知"原则的体现。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Sequence


@dataclass
class LLMContext:
    """传给 LLM 的完整上下文。框架负责组装, LLM 只负责生成。"""

    system: str = ""            # 人格硬约束 + 角色说明
    player_id: str | None = None    # 当前对话者 (千人千面的关键)
    memories: list[dict] = field(default_factory=list)  # 检索出的记忆
    question: str = ""          # 当前问题 / 待处理的玩家话语
    extra: dict[str, Any] = field(default_factory=dict)  # 计划、关系状态等


class LLMClient(ABC):
    """LLM 接口。实现者只应使用传入的记忆内容 (非全知原则)。"""

    @abstractmethod
    def complete(self, ctx: LLMContext) -> str:
        """对话/反应: 基于检索记忆生成一句回复。"""

    @abstractmethod
    def score_importance(self, text: str, player_id: str | None = None) -> float:
        """给一条记忆打重要性分 (1-10)。以玩家为参照系时, 关系事件应更高。"""

    @abstractmethod
    def reflection_questions(self, recent: Sequence[str]) -> list[str]:
        """从最近记忆里生成 3 个值得反思的高层问题。"""

    @abstractmethod
    def reflection_insights(self, evidence: list[tuple[int, str]],
                            n: int = 5) -> list[tuple[str, list[int]]]:
        """从证据 (id, 内容) 生成 n 条 Insight, 返回 (insight, 证据id列表)。"""

    @abstractmethod
    def generate_plan(self, persona_traits: dict[str, float],
                      previous_day: str, date: str) -> list[tuple[int, int, str]]:
        """生成日计划: 5-8 个 (start_hour, end_hour, activity) 时间块。"""

    @abstractmethod
    def decompose_activity(self, activity: str, start: int, end: int) -> \
            list[tuple[int, int, str]]:
        """把时间块分解为更细的 (start_hour, end_hour, subtask)。"""

    @abstractmethod
    def score_event(self, event: str, persona_traits: dict[str, float],
                    current_plan: str = "") -> tuple[float, float, float]:
        """判断事件价值, 返回 (社交价值, 目标价值, 打断代价), 各 0-10。

        取代关键词价值表: 让 LLM 对**任意**事件 (含没枚举过的) 做价值判断,
        而非查死表。社交价值 = 对这个人物的社交吸引力; 目标价值 = 与当前
        目标/计划的契合度; 打断代价 = 放下手头事去响应的损失。
        """
