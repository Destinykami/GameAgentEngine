"""LLM 层: LLMClient 抽象接口 + LLMContext 上下文。

框架让 LLM 承担十类推理, 全部抽象成接口方法:
- complete(ctx)                       对话/反应回复
- score_importance(text, player_id)   记忆重要性打分 (1-10)
- reflection_questions(recent)        生成反思用的 3 个高层问题
- reflection_insights(evidence, n)    从证据生成带引用的 Insight
- generate_plan(...)                  生成日计划
- decompose_activity(...)             把活动分解为子任务
- score_event(...)                    判断事件价值 (社交/目标/打断代价)
- judge_trust(...)                    基于关系记忆判断对玩家的信任度 (-1..1)
- judge_conflict(reflection, obs)     判断更晚观察与反思的矛盾强度 (0-10)
- perceive_action(npc, player, action)  NPC 把玩家的动作观察成自己的描述

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
                      previous_day: str, date: str,
                      context: str = "") -> list[tuple[int, int, str]]:
        """生成日计划: 5-8 个 (start_hour, end_hour, activity) 时间块。

        context 是 NPC 的近期记忆/世界事件 (如刚颁布的眼狩令)。计划在世界背景
        下生成: 情境紧张时计划应反映 (避开危险地、谨慎、检查藏匿处), 而非无视
        世界事件的岁月静好。context 为空时退回纯人格+前一天活动。
        """

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

    @abstractmethod
    def judge_trust(self, memories: list[tuple[str, str]],
                    player_id: str) -> float:
        """基于 NPC 对某玩家的关系记忆判断信任度, 返回 -1..1。

        memories 是 (类型, 内容) 列表 (观察 + 反思)。取代关键词词表计数:
        LLM 能理解"搭把手"=帮、"放鸽子"=背叛等花样措辞, 不会被词表漏判。
        -1 = 极度不信任/被背叛, 0 = 中立, +1 = 极度信任/可靠。
        """

    @abstractmethod
    def judge_conflict(self, reflection: str, observation: str) -> int:
        """判断一条更晚的观察与某条反思的矛盾强度, 返回 0-10 整数。

        取代词表方向匹配 (信任词 vs 背叛词): LLM 判语义矛盾。
        0 = 一致/无关, 5 = 部分矛盾(削弱), 10 = 强烈矛盾(直接推翻)。
        """

    @abstractmethod
    def perceive_action(self, npc_name: str, player_name: str, action: str,
                        context: str = "") -> str:
        """NPC 把玩家对它做的动作观察成自己的描述 (第三人称, 一句话)。

        脚本只提供原始动作 (动词+对象, 如"帮藏眼"/"委托打造武器"), NPC 结合
        自己的处境/记忆, 用第三人称客观描述"发生了什么" —— 观察内容由 NPC
        自己生成, 不是脚本写死的。context 是 NPC 该玩家近期记忆 (让描述连贯)。
        """
