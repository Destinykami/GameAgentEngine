"""事件反应的返回数据与纯效用规则，不访问记忆、模型或缓存。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ReactionDecision:
    react: bool
    action: str
    utility: float
    reason: str


def evaluate_response(event: str, persona_traits: dict[str, float],
                      values: tuple[float, float, float], trust: float = 0.0,
                      use_relationship: bool = True) -> ReactionDecision:
    v_social, v_goal, c_interrupt = values
    if use_relationship:
        trust_mod = max(0.0, 1.0 + trust)
    else:
        trust = 0.0
        trust_mod = 1.0
    w_social = persona_traits.get("social", 0.5) * trust_mod
    w_goal = persona_traits.get("goal_oriented", 0.5)

    utility = w_social * v_social + w_goal * v_goal - c_interrupt
    react = utility >= 0.0
    if react:
        action = f"接受并参与: {event}"
        reason = (f"效用 {utility:.2f} ≥ 0 (LLM判价值 社交{v_social:.0f}/"
                  f"目标{v_goal:.0f}/打断{c_interrupt:.0f}, "
                  f"社交权重{w_social:.2f}, 目标权重{w_goal:.2f}, 信任{trust:+.2f})")
    else:
        action = f"婉拒: {event}, 继续当前安排"
        reason = (f"效用 {utility:.2f} < 0 (LLM判价值 社交{v_social:.0f}/"
                  f"目标{v_goal:.0f}/打断{c_interrupt:.0f}, "
                  f"目标价值高或信任不足)")
    return ReactionDecision(react=react, action=action,
                            utility=utility, reason=reason)
