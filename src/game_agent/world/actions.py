"""动作执行：只依赖显式物理上下文与窄服务，不持有 World。"""

from __future__ import annotations

import random
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Protocol

from .events import VisualEvent
from .entities import Entity, Location, distance


class ActionCognition(Protocol):
    def observe(self, content: str, now: float,
                player_id: str | None = None) -> int: ...

    def speak(self, player_id: str, utterance: str, now: float,
              remember: bool = True, record_utterance: bool = True) -> str: ...


@dataclass(frozen=True)
class ActionContext:
    clock: float
    entities: Mapping[str, Entity]
    locations: Mapping[str, Location]
    perception_radius: float
    threat_filter: Callable[[Entity, Entity], bool] | None
    visual_events: list[VisualEvent]
    rumor_spread: bool
    interact_actions: tuple[str, ...]


@dataclass(frozen=True)
class ActionServices:
    npc: Callable[[str], ActionCognition | None]
    observe_social: Callable[[Entity, Entity, str], ActionCognition | None]
    spread_rumor: Callable[[Entity, Entity, str], None]
    run_effects: Callable[[str, Entity, Entity | None, dict, VisualEvent], None]
    record_chain: Callable[[Entity, str, Entity], None]


def normalize_action(action) -> dict:
    """R7: 动作输入在入口做 schema 校验/降级, 防非法值流进对话/LLM prompt 链。

    - 非 dict 动作 → 降级为 wait (不崩)。
    - utterance 为 None → 降级空串 (旧实现 get('utterance','') 在显式传 None 时
      返回 None, f-string 强转成字符串"None" —— 不崩但语义垃圾, 喂给对话检索/LLM)。
    - utterance 非字符串 (如数字) → 强转字符串 (保留信息, 不丢弃)。
    返回规整后的新 dict, 不改调用方的。action/target/dest 的合法性由下游
    is_alive / locations 检查兜底, 这里只管类型。
    """
    if not isinstance(action, dict):
        return {"action": "wait"}
    norm = dict(action)
    utterance = norm.get("utterance")
    if utterance is None:
        norm["utterance"] = ""
    elif not isinstance(utterance, str):
        norm["utterance"] = str(utterance)
    return norm

def within_reach(agent: Entity, target: Entity | None, radius: float) -> bool:
    return (target is not None and target is not agent and target.is_alive()
            and distance(agent, target) <= radius)


def emit_failure(context: ActionContext, action_type: str, agent: Entity,
                 target: Entity | None, target_name: str, reason: str) -> str:
    event = VisualEvent(
        "conversation" if action_type == "talk" else action_type,
        agent.name, context.clock, location=agent.location.name,
        target=target.name if target is not None else target_name,
        success=False, failure_reason=reason)
    context.visual_events.append(event)
    return event.describe()


class ActionExecutor:
    def execute(self, agent: Entity, action: dict, context: ActionContext,
                services: ActionServices) -> str:
        """执行动作并应用影响, 返回发生了什么 (供打印/记录)。非全知: 只影响直接相关方。

        结构化视觉事件是单一事实源: 每个分支产出 VisualEvent 追加进
        context.visual_events, 返回的字符串由 ve.describe() 派生 (与旧实现逐字一致)。
        前端回放读 visual_events, 不再解析中文事件串。
        """
        action = normalize_action(action)   # R7: 入口 schema 校验/降级
        a = action.get("action", "wait")
        target = context.entities.get(action.get("target", "")) if action.get("target") else None
        # F3-3: 目标在视距外/已死/不存在 → 动作中止, 不扣血/不写历史/不对话。
        if (a in context.interact_actions and action.get("target")
                and not within_reach(agent, target, context.perception_radius)):
            return emit_failure(context,
                a, agent, target, action.get("target", ""), "不在可交互范围")
        def emit(ve: VisualEvent) -> str:
            """追加结构化事件并返回其派生字符串。"""
            context.visual_events.append(ve)
            return ve.describe()

        if a == "move":
            dest = action.get("dest") or agent.location.name
            if dest in context.locations:
                agent.move(context.locations[dest])
                agent.record(f"移动到 {dest}")
                return emit(VisualEvent("move", agent.name, context.clock,
                                        location=agent.location.name, to=dest))
            return emit(VisualEvent("move", agent.name, context.clock,
                                    location=agent.location.name, to=dest,
                                    success=False,
                                    failure_reason=f"目标区域 {dest} 不存在"))
        if a == "talk" and target and target.is_alive():
            line = action.get("utterance", "")
            # R6: 原子性 —— 可失败的认知事件生成在前 (observe + speak, LLM/embedding
            # 可能失败), 成功才提交历史/理由/锻刀 (最终状态)。失败则中止动作 (不写
            # 历史/不积理由/不锻刀), 不留"历史已写但没观察到/没回话"的撕裂。目标不
            # 是 NPC 则无认知事件, 直接提交。speak 内部门控: full 档且出现新观察才
            # 重跑关系反思, 再走对话检索+回复。
            reply = ""
            if services.npc(target.name) is not None:
                try:
                    npc = services.observe_social(target, agent, f"对TA说: {line}")
                    if npc is not None:
                        # 对方话语已经由 _observe_target_social/perceive_action
                        # 观察入库, speak 只补记自己的回复, 避免双写 incoming。
                        reply = npc.speak(agent.name, line, context.clock,
                                          record_utterance=False) or ""
                except Exception:
                    return emit(VisualEvent(
                        "conversation", agent.name, context.clock,
                        location=agent.location.name, target=target.name,
                        utterance=line, success=False,
                        failure_reason="认知事件生成失败"))
            # 自观察回流: 说话者是 NPC 时, 把自己这句话 observe 进自己记忆流
            # (player_id=目标, "我对 B 说: X")。与"回复回流"对称 —— 此前自己的话只进
            # 动作历史 (decide_action 的临时近期事件), 不进长期记忆流, NPC 没有"我说过
            # 什么"的记忆 (例如答应过什么)。现在说话者既记得对方说的 (回复回流), 也记得
            # 自己说的 (本行), 对话双向+自洽落记忆。说话者是玩家 (无认知对象) 时跳过。
            # best-effort: 失败不中止已成功的对话。自观察的反馈风险 (反复读自己的话)
            # 由 0.92 去重 + 夜间固化消化, 不在此处特判。
            if line and services.npc(agent.name) is not None:
                try:
                    services.npc(agent.name).observe(f"我对 {target.name} 说: {line}",
                                                   context.clock, player_id=target.name)
                except Exception:
                    pass
            # 回复回流: 说话者是 NPC 时, 把对方回复 observe 进自己记忆流 (player_id=目标)。
            # 闭合此前的非对称 —— 旧实现里回复只进回放事件, 说话者的后续决策看不到
            # 对方答了什么, NPC 间"对话"退化成各自基于自己记忆的一串独白 (LLM 靠
            # 脑补补出"我确认过了")。现在双方对称: 接收方记得说话者的话 (既有
            # perceive_action), 说话者也记得接收方的回复 (本行)。说话者是玩家 (无认知
            # 对象) 时跳过。best-effort: 回流 observe 失败不中止已成功的对话 (回复
            # 仍在回放事件里), 只丢这条记忆写入。
            if reply and services.npc(agent.name) is not None:
                try:
                    services.npc(agent.name).observe(f"{target.name} 说: {reply}",
                                                   context.clock, player_id=target.name)
                except Exception:
                    pass
            agent.record(f"对 {target.name} 说: {line}")
            target.record(f"{agent.name} 对TA说: {line}")
            # S4 谣言传播 (缺省关): 这句话被范围内第三方听到 + 说话者 NPC 可能
            # 把持有的传闻转述给对话者。关时零行为。
            if context.rumor_spread and line:
                services.spread_rumor(agent, target, line)
            ve = VisualEvent("conversation", agent.name, context.clock,
                             location=agent.location.name, target=target.name,
                             utterance=line, reply=reply, reply_speaker=target.name)
            # 世界层效果 (理由生成/锻刀等具体世界行为) 由情境经钩子注入, 引擎不再硬编码。
            services.run_effects("talk", agent, target, action, ve)
            # F6-5: 行为链只在动作成功提交后计数 (失败/中止不推进)。
            services.record_chain(agent, a, target)
            return emit(ve)
        if a == "attack" and target and target.is_alive():
            dmg = max(0, agent.attack - target.defense + random.randint(-2, 2))
            will_die = target.health - dmg <= 0   # 预判死亡 (提交后 target.dead 才定)
            # R6: 原子性 —— 可失败的认知事件生成在前, 成功才提交物理状态+历史。
            # 目标 NPC 先 observe (LLM/embedding 可能失败), 成功才扣血, 避免"血已扣
            # 但 NPC 没观察到、反思队列没登记"的撕裂。失败则中止 (不扣血/不记历史)。
            # 挨打的"反应"由目标下一步 decide_agent 行动承担 (逃跑/反击), 不在此回话。
            if services.npc(target.name) is not None:
                try:
                    services.observe_social(
                        target, agent,
                        f"攻击了TA, 造成 {dmg} 伤害" + ("(致TA阵亡)" if will_die else ""))
                except Exception:
                    return emit(VisualEvent(
                        "attack", agent.name, context.clock,
                        location=agent.location.name, target=target.name,
                        success=False, failure_reason="认知事件生成失败"))
            # 认知事件生成成功 (或目标非 NPC) → 提交物理状态 + 历史
            target.take_damage(dmg)
            agent.record(f"攻击 {target.name}, 造成 {dmg} 伤害")
            target.record(f"{agent.name} 攻击了TA, 受到 {dmg} 伤害")
            ve = VisualEvent("attack", agent.name, context.clock,
                             location=agent.location.name, target=target.name,
                             damage=dmg, target_dead=target.dead)
            # 世界层效果 (如"执行官收缴持眼者→目击者得理由") 由情境经钩子注入。
            services.run_effects("attack", agent, target, action, ve)
            # F6-5: 行为链只在攻击成功提交后计数。
            services.record_chain(agent, a, target)
            return emit(ve)
        if a == "flee":
            # 逃到离最近威胁最远的区域
            threats = [o for o in context.entities.values()
                       if o is not agent and not o.dead
                       and distance(agent, o) <= context.perception_radius
                       and (context.threat_filter is None
                            or context.threat_filter(agent, o))]
            if threats:
                def farthest(loc: Location) -> float:
                    return min(((loc.x - t.location.x) ** 2 +
                                (loc.y - t.location.y) ** 2) ** 0.5
                               for t in threats)
                best = max(context.locations.values(), key=farthest)
                agent.move(best)
                agent.record(f"逃离威胁, 逃到 {best.name}")
                return emit(VisualEvent("flee", agent.name, context.clock,
                                        location=agent.location.name, to=best.name))
            return emit(VisualEvent("flee", agent.name, context.clock,
                                    location=agent.location.name, success=False,
                                    failure_reason="无威胁可逃"))
        if a in ("help", "hide") and target and target.is_alive():
            # F3-4: 与 attack/talk 对齐 —— 可失败的认知事件在前, 成功才提交
            # history/effects; 失败中止动作, 不留"状态已改但 NPC 没观察到"。
            try:
                services.observe_social(
                    target, agent, "帮助了TA" if a == "help" else "替TA藏匿")
            except Exception:
                return emit_failure(context,
                    a, agent, target, target.name, "认知事件生成失败")
            agent.record(f"{'帮助' if a == 'help' else '替'} {target.name}")
            target.record(f"{agent.name} {'帮了TA' if a == 'help' else '替TA藏匿'}")
            ve = VisualEvent(a, agent.name, context.clock,
                             location=agent.location.name, target=target.name)
            # E16: 目标 NPC 观察这次帮助/藏匿进自己记忆流 (关系认知, 信任度随之
            # 惰性上升)。目标非 NPC 时 _observe_target_social 返回 None, 无认知事件。
            # 世界层效果 (如"帮持眼者→得理由") 由情境经钩子注入。
            services.run_effects(a, agent, target, action, ve)
            # F6-5: 行为链只在帮助/藏匿成功提交后计数。
            services.record_chain(agent, a, target)
            return emit(ve)
        agent.record("观望")
        return emit(VisualEvent("wait", agent.name, context.clock,
                                location=agent.location.name))

