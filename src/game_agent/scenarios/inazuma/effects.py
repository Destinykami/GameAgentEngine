"""稻妻动作效果与证据生成；由场景显式注入 World。"""

from .definition import WEAPON_GAIN, WEAPON_CAP

def _generate_reason(world, agent, target, utterance: str, reply: str) -> str | None:
    """B+ 涌现: 让 LLM 从这次对话里提炼一条关于眼狩令之弊的"新证据"。

    新颖性对照: 把已收集的证据喂进去, 要求 LLM 只给"没见过"的; 确无新证据则回 NONE
    (不硬凑)。去重双保险: LLM 新颖性判断是语义去重, add_reason 的文本去重是兜底。
    无 LLM / 调用失败 → None (不强行生成)。证据文本从此是活的, 不再是写死的槽位。
    """
    llm = world.agent_model(agent.name)
    if llm is None or not hasattr(llm, "ask"):
        return None
    known = " / ".join(agent.reasons) if agent.reasons else "尚无"
    prompt = (
        f"旅行者与{target.name} (角色: {target.role or '百姓'}) 交谈。\n"
        f"旅行者说: {utterance}\n{target.name}答: {reply}\n"
        f"旅行者已收集的证据: {known}\n"
        "任务: 从这段对话中提炼旅行者新得到的、关于眼狩令之弊的一条'新证据/看法', "
        "且必须不在已收集证据里。确无新证据就输出 NONE; 否则用一句第三人称概括 "
        "(不要照抄对话原文)。"
    )
    try:
        raw = llm.ask(prompt, system="你在提炼证据, 只输出一句概括, 或 NONE。",
                      max_tokens=80).strip()
    except Exception:
        return None
    if not raw or raw.upper() == "NONE" or raw.startswith("无"):
        return None
    return raw


def inazuma_talk_effect(world, agent, target, action, ve) -> None:
    # 证据 (仅玩家积累): LLM 从这次对话生成 (涌现), 对照已收集证据做新颖性去重
    if agent.kind == "player":
        r = _generate_reason(world, agent, target, action.get("utterance", ""), ve.reply)
        if r and agent.add_reason(r, world.reason_cap):
            ve.reason_added = r
            ve.reason_count = len(agent.reasons)
        elif r:
            # 去重反馈: 证据重复不新增, 写入行动者历史让 LLM 看得见 "这条没算数",
            # 别把同一来源问到底 (静默丢弃会让 LLM 误以为已积累、原地反复对话)。
            agent.record(f"向 {target.name} 取的证据重复, 未新增 (现{len(agent.reasons)}条)")
    # 铁匠: 对话 = 锻一把武器, 攻提升 (与证据独立, 找铁匠既取证又锻刀)
    if "blacksmith" in target.role and agent.attack < WEAPON_CAP:
        agent.attack = min(WEAPON_CAP, agent.attack + WEAPON_GAIN)
        ve.weapon_attack = agent.attack


def inazuma_attack_effect(world, agent, target, action, ve) -> None:
    # 执行官收缴持眼者 → 同地点的目击玩家积累一条理由 (亲眼所见)
    if "enforcer" in agent.role and "vision_holder" in target.role:
        for witness in world.entities.values():
            if (witness.kind == "player" and witness is not agent
                    and witness is not target and witness.is_alive()
                    and witness.location is target.location):
                if witness.add_reason(
                        f"目睹执行官当众收缴 {target.name} 的神之眼, 其家破人亡",
                        world.reason_cap):
                    ve.witnessed = True
                    ve.reason_count = len(witness.reasons)
                else:
                    witness.record(f"目睹收缴 {target.name} 的理由已重复, 未新增 "
                                   f"(现{len(witness.reasons)}条)")


def inazuma_help_effect(world, agent, target, action, ve) -> None:
    # 帮持眼者护住神之眼 = 一条反眼狩令的理由 (仅玩家, 仅 help 动作)
    if action.get("action") == "help" and agent.kind == "player" \
            and "vision_holder" in target.role:
        r = f"助 {target.name} 藏好神之眼, 令其免遭收缴"
        if agent.add_reason(r, world.reason_cap):
            ve.reason_added = r
            ve.reason_count = len(agent.reasons)
        else:
            agent.record(f"帮 {target.name} 藏匿的理由已重复, 未新增 "
                         f"(现{len(agent.reasons)}条)")


def register_scenario(world) -> None:
    """把稻妻情境的动作效果注册进引擎 (引擎与世界行为解耦的注入点)。"""
    world.add_action_effect("talk", inazuma_talk_effect)
    world.add_action_effect("attack", inazuma_attack_effect)
    world.add_action_effect("help", inazuma_help_effect)
    world.add_action_effect("hide", inazuma_help_effect)
