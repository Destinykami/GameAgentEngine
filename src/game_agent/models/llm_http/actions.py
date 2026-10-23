"""原任务提示词及结果转换；只依赖传入的请求能力。"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Sequence


def decide_action(request: Callable[..., Any], agent_name: str, goal: str,
                  persona_traits: dict[str, float], perception: str,
                  history: list[str], state: str) -> dict:
    """Agent 决策下一步动作 (非全知)。输出结构化动作 JSON。"""
    hist = "\n".join(f"- {h}" for h in history[-10:]) or "(无)"
    user = ("你是游戏角色「" + agent_name + "」。你的目标: " + (goal or "(无)")
            + "。人格特质: " + str(persona_traits) + "。\n"
            + "你当前看到的 (非全知, 仅视距内): " + (perception or "(空无一人)") + "\n"
            + "你近期的经历:\n" + hist + "\n"
            + "你的状态: " + state + "\n\n"
            + "基于以上, 决定你下一步做什么。输出 JSON 对象:\n"
            + '{"action": "move"|"talk"|"attack"|"help"|"hide"|"flee"|"wait",'
            + ' "target": "对象名或空", "utterance": "若对话说什么, 否则空",'
            + ' "dest": "若移动去哪区域, 否则空", "reason": "简述理由"}\n'
            + "action 选一个; 只输出 JSON。")
    try:
        data = request("你是一个游戏角色决策器, 只输出一个 JSON 对象。",
                               user, think=False, temperature=0.2,
                               _stats_tag="decide_action")
    except (ValueError, RuntimeError):
        # 解析失败 (模型截断 JSON 等) 或网络重试耗尽 (RuntimeError) 兜底
        # wait: 一条坏输出/一次超时不能拖垮整个 World.step 自治循环
        # (同 _parse_hour 的防御原则)。
        return {"action": "wait", "target": "", "utterance": "",
                "dest": "", "reason": "决策解析失败"}
    if isinstance(data, dict) and "action" in data:
        return {"action": str(data.get("action", "wait")),
                "target": str(data.get("target", "")),
                "utterance": str(data.get("utterance", "")),
                "dest": str(data.get("dest", "")),
                "reason": str(data.get("reason", ""))}
    return {"action": "wait", "target": "", "utterance": "",
            "dest": "", "reason": "解析失败"}



def score_event(request: Callable[..., Any], event: str, persona_traits: dict[str, float],
                current_plan: str = "") -> tuple[float, float, float]:
    """让 LLM 判断事件价值 (社交/目标/打断代价), 各 0-10。取代关键词死表。"""
    plan_line = ("当前正忙: " + current_plan) if current_plan else "当前没有特别重要的计划。"
    user = ("为一个 NPC 判断下面这个事件的价值。人格特质: "
            + str(persona_traits) + "。\n" + plan_line + "\n\n"
            + "事件: " + event + "\n\n"
            + "判断三个维度, 各打 0 到 10 的整数:\n"
            + "- v_social 社交价值: 这件事对这个人物有多大的社交吸引力/参与价值\n"
            + "- v_goal 目标价值: 这件事与他当前目标/计划的契合度\n"
            + "- c_interrupt 打断代价: 放下手头事去响应这件事的损失\n\n"
            + '输出 JSON, 例如 {"v_social": 8, "v_goal": 1, "c_interrupt": 3}。')
    data = request("你是一个事件价值评估器, 只输出 JSON。", user,
                           think=False, temperature=0.0, max_tokens=128,
                           _stats_tag="score_event")
    if not isinstance(data, dict):
        return (3.0, 3.0, 2.0)
    def _clip(key: str, default: float) -> float:
        try:
            return max(0.0, min(10.0, float(data.get(key, default))))
        except (TypeError, ValueError):
            return default
    return (_clip("v_social", 3.0), _clip("v_goal", 3.0),
            _clip("c_interrupt", 2.0))
