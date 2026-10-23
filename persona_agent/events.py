"""结构化事件与兼容输出；不依赖世界执行、场景或模型。"""

from __future__ import annotations

from dataclasses import dataclass

# --------------------------------------------------------------------- 视觉事件
@dataclass
class VisualEvent:
    """结构化视觉事件 (渲染层的单一事实源)。

    execute_action / world_event 产出它, 显示字符串由 describe() 派生 —— 字符串
    与语义字段同源, 永不漂移 (前端不再需要解析中文事件串)。type 为判别字段,
    其余字段仅对特定类型有意义:

    - move:        actor, to                          移动到某区域
    - conversation: actor, target, utterance, reply,  成功对话 (reply_speaker 通常 = target)
                   reply_speaker (+ reason/weapon 系统效果)
    - attack:      actor, target, damage, target_dead 攻击 (target_dead = 此击致死)
    - help / hide: actor, target (+ reason 系统效果)
    - flee:        actor, to                          逃离威胁
    - wait:        actor                              观望
    - world_event: description                        全图/局部世界事件

    success=False 表示动作中止 (认知事件生成失败等): 此时只有 actor/target/
    failure_reason 有意义, 不携带 reply/damage 等成功态字段 —— 渲染层据此不显示
    完成态气泡或伤害动画。reason/weapon/witnessed 是"系统效果", 用独立字段
    而非塞进 utterance, 渲染层可单独渲染为系统提示。
    """
    type: str
    actor: str
    clock: float
    location: str = ""             # 动作发生所在区域
    target: str = ""               # 作用对象 (talk/attack/help/hide)
    to: str = ""                   # 移动/逃跑的目的地区域
    utterance: str = ""            # conversation: 行动者台词
    reply: str = ""                # conversation: 目标 NPC 回复
    reply_speaker: str = ""        # conversation: 回复者 (通常 = target)
    damage: int = 0                # attack: 造成的伤害
    target_dead: bool = False      # attack: 目标是否因此击阵亡
    success: bool = True           # False = 动作中止 (认知事件生成失败等)
    failure_reason: str = ""       # 中止原因 (仅进日志, 不触发完成态动画)
    reason_added: str = ""         # 系统效果: 新增的理由文本 (player 积累)
    reason_count: int = 0          # 系统效果: 加理由后的条数 (marker 用)
    weapon_attack: int = 0         # 系统效果: 铁匠锻刀后玩家攻值 (0 = 未锻)
    witnessed: bool = False        # attack: 执行官收缴持眼者被玩家目击 (加理由)
    description: str = ""          # world_event: 事件描述

    def describe(self) -> str:
        """派生显示字符串, 与既有 execute_action 逐字一致 (向后兼容)。"""
        a = self.actor
        if self.type == "move":
            if not self.success:
                return f"{a} 想移动到不存在的 {self.to}, 未动"
            return f"{a} 移动到 {self.to}"
        if self.type == "conversation":
            if not self.success:
                reason = self.failure_reason or "认知事件生成失败"
                return (f"{a} 想对 {self.target} 说话, "
                        f"但{reason}, 动作中止")
            out = f"{a} 对 {self.target} 说: {self.utterance}"
            if self.reply:
                out += f" ← {self.reply_speaker}: {self.reply}"
            if self.reason_added:
                out += f" [旅行者积累理由, 现{self.reason_count}条]"
            if self.weapon_attack:
                out += f" [刚郎锻好武器, {a}攻升至{self.weapon_attack}]"
            return out
        if self.type == "attack":
            if not self.success:
                reason = self.failure_reason or "认知事件生成失败"
                return (f"{a} 想攻击 {self.target}, "
                        f"但{reason}, 动作中止")
            out = f"{a} 攻击 {self.target}, 造成 {self.damage} 伤害"
            if self.target_dead:
                out += f" → {self.target} 阵亡!"
            if self.witnessed:
                out += f" [旅行者目击搜捕, 积累理由现{self.reason_count}条]"
            return out
        if self.type == "flee":
            if not self.success:
                return f"{a} 想逃但无威胁"
            return f"{a} 逃离威胁, 逃到 {self.to}"
        if self.type == "help":
            if not self.success:
                reason = self.failure_reason or "动作中止"
                return f"{a} 想帮助 {self.target}, 但{reason}"
            out = f"{a} 帮助 {self.target}"
            if self.reason_added:
                out += f" [旅行者积累理由, 现{self.reason_count}条]"
            return out
        if self.type == "hide":
            if not self.success:
                reason = self.failure_reason or "动作中止"
                return f"{a} 想替 {self.target} 藏匿, 但{reason}"
            return f"{a} 替 {self.target}"
        if self.type == "world_event":
            return f"世界事件: {self.description}"
        return f"{a} 观望"

    def to_dict(self) -> dict:
        """序列化为 JSON 友好的 dict (供 timeline 的 visual_events 字段)。

        只保留非空/非默认字段, 保持紧凑; type/actor/clock 恒保留。
        """
        d: dict = {"type": self.type, "actor": self.actor, "clock": self.clock}
        if self.location:
            d["location"] = self.location
        if self.target:
            d["target"] = self.target
        if self.to:
            d["to"] = self.to
        if self.type == "conversation":
            d["utterance"] = self.utterance
            if self.reply:
                d["reply"] = self.reply
            if self.reply_speaker:
                d["reply_speaker"] = self.reply_speaker
        if self.type == "attack" and self.success:
            d["damage"] = self.damage
            d["target_dead"] = self.target_dead
        if not self.success:
            d["success"] = False
            if self.failure_reason:
                d["failure_reason"] = self.failure_reason
        if self.reason_added:
            d["reason_added"] = self.reason_added
            d["reason_count"] = self.reason_count
        if self.weapon_attack:
            d["weapon_attack"] = self.weapon_attack
        if self.witnessed:
            d["witnessed"] = True
            d["reason_count"] = self.reason_count   # 目击事件同样带理由条数, 前端不再显示 undefined
        if self.type == "world_event":
            d["description"] = self.description
        return d


