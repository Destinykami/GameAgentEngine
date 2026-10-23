"""原任务提示词及结果转换；只依赖传入的请求能力。"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Sequence

from ..llm import LLMContext

def complete(request: Callable[..., str], ctx: LLMContext, *, thinking: bool = False) -> str:
    memories = ctx.memories or []
    if not memories:
        return "我对此没有印象。"

    def _mem_line(m: dict) -> str:
        # 被削弱的反思 (confidence<1) 显式标注置信度, 让 NPC 引用被部分推翻的
        # 信念时带着相应的犹疑; 观察/计划恒 1.0, 保持原样不注水。
        if m.get("type") == "reflection" and m.get("confidence", 1.0) < 0.999:
            return f"- [反思] (置信度{m['confidence']:.2f}) {m['content']}"
        return f"- [{m['type']}] {m['content']}"

    mem_lines = "\n".join(_mem_line(m) for m in memories)
    who = f"当前和你说话的人是 {ctx.player_id}。" if ctx.player_id else ""
    user = (who + "\n你记得的事情 (只准用这些, 没提到的就当不知道):\n"
            + mem_lines + "\n带'置信度'的记忆已被后来的事情部分推翻, "
            "引用时语气要留有余地。\n\n对方说: " + ctx.question
            + "\n\n用第一人称、符合你性格地回应对方。只说一两句。")
    return request(ctx.system or "你是一个游戏 NPC, 只用你记得的事说话。",
                      user, think=thinking, temperature=0.7, max_tokens=256,
                      _stats_tag="complete")


def perceive_action(request: Callable[..., str], npc_name: str, player_name: str, action: str,
                    context: str = "") -> str:
    """NPC 把对方的动作观察成自己的描述 (第三人称)。观察内容由 NPC 生成。"""
    ctx_line = ("你目前关于" + player_name + "的记忆: " + context + "\n") if context else ""
    user = ("你是游戏 NPC「" + npc_name + "」。「" + player_name
            + "」刚刚对你做了这样一件事: " + action + "。\n" + ctx_line
            + "\n用第三人称客观描述你观察到的这件事 (一句话): 称自己为你的名字"
            + "「" + npc_name + "」, 称对方为「" + player_name
            + "」, 只描述动作事实, 不加评价、不揣测动机。直接输出这句话。")
    return request("你是游戏 NPC 的观察者, 客观描述你看到的事, 只输出一句话。",
                      user, think=False, temperature=0.4, max_tokens=64,
                      _stats_tag="perceive_action").strip()
