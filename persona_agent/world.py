"""world.py: 游戏世界层 —— 空间、实体、距离、世界状态持久化。

阶段 0 (世界骨架): 提供 Location / Entity / Player / World, 游戏时钟, 位置,
距离度量, 以及 World.save/load。世界状态单独存 world.db (实体位置 + 时钟),
与每个 NPC 的独立 db 分离, 不破坏"一 NPC 一库"约定。

阶段 0 不含感知 / 档位调度 / NPC 认知 —— 那些由后续阶段接入 (见 WorldPlan.md):
  阶段 1 多 NPC 注册, 阶段 2 空间感知, 阶段 3 距离调度, 阶段 4 世界事件,
  阶段 5 模拟驱动, 阶段 6 稻妻城·眼狩令 demo。
"""

from __future__ import annotations

import json
import os
import random
import sqlite3
import threading
from dataclasses import dataclass, field

from .memory import HEARSAY_MAX_HOP   # 传闻链上限 (S4); memory 不依赖 world, 无循环


# --------------------------------------------------------------------- 区域
@dataclass(frozen=True)
class Location:
    """有坐标的空间 (稻妻城: 主城街道 / 治疗堂 / 锻造坊 / 眼狩署 / 神樱庭)。"""
    name: str
    x: float = 0.0
    y: float = 0.0


# --------------------------------------------------------------------- 实体
@dataclass
class Entity:
    """世界实体 (Agent): NPC 或玩家, 都有位置 + 物理状态 + 目标。

    kind = "npc" | "player"。多智能体自治 (world_auto_sim) 里每个实体都是
    Agent: 感知 (非全知) → 决策 → 行动。物理状态 (血/攻防) 供战斗, goal 驱动
    决策, history 是自身近期事件 (决策用的非全知视图, 不读别人记忆)。
    """
    kind: str
    name: str
    location: Location
    health: int = 100          # 血量, 0 = 死亡
    attack: int = 10           # 攻击 (伤害 = 攻 - 对方防 + 随机)
    defense: int = 0           # 防御
    goal: str = ""             # 目标 (LLM 决策的驱动力)
    dead: bool = False         # 死亡标记 (移出世界)
    role: str = ""             # 角色 (vision_holder/blacksmith/scholar/enforcer/shogun...)
    history: list[str] = field(default_factory=list)   # 自身近期事件 (非全知视图)
    reasons: list[str] = field(default_factory=list)   # 积累的理由/证据 (说服用, 见 world_auto_sim)

    def move(self, location: Location) -> None:
        self.location = location

    def is_alive(self) -> bool:
        return not self.dead

    def take_damage(self, dmg: int) -> int:
        """承受伤害, 返回实际扣血; 归零死亡。"""
        if self.dead:
            return 0
        self.health -= dmg
        if self.health <= 0:
            self.health = 0
            self.dead = True
        return dmg

    def record(self, event: str) -> None:
        """记入自身近期事件 (决策用的非全知视图), 上限 20 条。"""
        self.history.append(event)
        self.history = self.history[-20:]

    def add_reason(self, reason: str, cap: int) -> bool:
        """积累一条理由/证据 (说服用)。达上限或重复则不加。返回是否新增。"""
        if reason in self.reasons or len(self.reasons) >= cap:
            return False
        self.reasons.append(reason)
        return True


class Player(Entity):
    """玩家 Agent (kind=player)。多智能体自治里是 LLM 驱动的 agent (有 goal)。"""
    def __init__(self, name: str, location: Location,
                 goal: str = "", health: int = 100,
                 attack: int = 10, defense: int = 0) -> None:
        super().__init__(kind="player", name=name, location=location,
                         health=health, attack=attack, defense=defense,
                         goal=goal)


# --------------------------------------------------------------------- 距离
def distance(a: Entity, b: Entity) -> float:
    """两个实体间的欧氏距离 (同位置 = 0)。档位调度 (阶段 3) 以此为准。"""
    return ((a.location.x - b.location.x) ** 2 +
            (a.location.y - b.location.y) ** 2) ** 0.5


def location_distance(loc: Location, ent: Entity) -> float:
    """某区域到某实体的欧氏距离。世界事件 (阶段 4) 以事件地点为中心算影响半径。"""
    return ((loc.x - ent.location.x) ** 2 +
            (loc.y - ent.location.y) ** 2) ** 0.5


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
                return (f"{a} 想对 {self.target} 说话, "
                        f"但认知事件生成失败, 动作中止")
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
                return (f"{a} 想攻击 {self.target}, "
                        f"但认知事件生成失败, 动作中止")
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
            out = f"{a} 帮助 {self.target}"
            if self.reason_added:
                out += f" [旅行者积累理由, 现{self.reason_count}条]"
            return out
        if self.type == "hide":
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


# --------------------------------------------------------------------- 世界
class World:
    """游戏世界: 持有区域、实体注册表、游戏时钟。

    世界状态单独持久化在 world.db (实体位置 + 时钟), 与每个 NPC 的独立 db 分离。
    不传 path 则为内存世界 (不可持久化, 供离线骨架测试)。
    """

    # 打断当日计划、触发重规划的动作 (M5): 战斗/逃跑/帮匿都是"日程被打破"的
    # 重大状态变化。talk/move/wait 是日程内的日常行为, 不打断。
    INTERRUPT_ACTIONS = ("attack", "counterattack", "flee", "help", "hide")

    def __init__(self, name: str, locations: list[Location],
                 path: str | None = None,
                 perception_radius: float = 1.5,
                 full_radius: float = 0.5,
                 force_full_tier: bool = False,
                 decision_tier_gate: bool = False,
                 social_perception: bool = False,
                 rumor_spread: bool = False,
                 consolidation: bool = False,
                 use_identity_beliefs: bool = False,
                 consolidate_hour: float = 23.0) -> None:
        self.name = name
        self.locations: dict[str, Location] = {loc.name: loc for loc in locations}
        self.entities: dict[str, Entity] = {}
        self._npcs: dict[str, "NPC"] = {}   # NPC 认知对象 (实体注册表的子集)
        self._npc_data_dirs: dict[str, str] = {}   # NPC → 其独立 db 的 data_dir (持久化注册表)
        self._agent_llms: dict[str, object] = {}   # agent → 其 LLM (决策用, 自治循环)
        self._agent_personas: dict[str, dict] = {}   # agent → 人格特质 (决策用)
        self.reason_cap = 3          # 一个 agent 最多积累几条理由/证据 (通用容量, 情境可覆盖)
        self.clock: float = 0.0            # 游戏内时间 (小时, 单调递增)
        self.perception_radius = perception_radius   # 视距: 玩家距 NPC 超过则感知不到
        self.full_radius = full_radius             # 同区域半径: 玩家距 NPC <= 此值 = full
        # 消融开关 (缺省 False = 现行为): True 时全员全认知, 跳过距离调度 ——
        # 调度效率实验的 all-full 基线。
        self._force_full_tier = force_full_tier
        # 档位决策门控 (缺省 False = 现行为): True 时 idle 档 NPC 走规则等待
        # (零 LLM), 不跑 decide_action —— 三级认知调度在决策层的落点: 视距内
        # 无人时, 远处 NPC 不需要 LLM 战略决策。玩家 agent 不受门控 (玩家不归档)。
        self._decision_tier_gate = decision_tier_gate
        # S2 社交在场感知 (缺省 False = 现行为): NPC 感知视距内其他 NPC 的**出现**,
        # 生成 per-entity 关系观察 (与 E16 社交动作观察同流, 信任/关系反思机制复用)。
        # 过渡驱动: 只对"新出现在视距内"的 NPC 产生观察, 重复在场不重复入库
        # (离开后重现会再触发)。idle 档经 perceive 入口早退自动排除。
        self._social_perception = social_perception
        # 每 NPC 当前视距内的 NPC 名集合 (出现检测的内存态, 同 _plan_blocks 不持久化)
        self._social_seen: dict[str, set[str]] = {}
        # S4 谣言传播 (缺省 False = 现行为): talk 的话语被范围内第三方 NPC 听到
        # (传闻观察 hop=1), 持有未封顶传闻的 NPC 下次谈吐时转述给对话者 (hop+1)。
        # S5 内生事件钩子: {action: (阈值, 描述)} —— 同一 actor 对同一 target 连续
        # 同型动作达阈值触发世界事件 (链断重置), 与 add_action_effect 同族:
        # 引擎只计数分派, 规则语义由世界层注册, 缺省无规则 = 现行为。
        self._rumor_spread = rumor_spread
        self._chain_rules: dict[str, tuple[int, str]] = {}
        self._chain_counters: dict[str, dict[tuple[str, str], int]] = {}
        # M1 记忆固化 (缺省关): 每晚 consolidate_hour 把当天观察压缩成 episode。
        # M3 身份信念注入 (缺省关): 开启后 decide_agent 把身份信念拼进感知上下文。
        self._consolidation = consolidation
        self._use_identity_beliefs = use_identity_beliefs
        self._consolidate_hour = consolidate_hour
        self._last_consolidate_day = -1
        self.path = path
        self._conn: sqlite3.Connection | None = None
        self._lock = threading.RLock()
        self._last_plan_day = -1   # 已生成过日计划的天 (0-based); step 每天早晨自动规划
        # E16: 本步发生的社交交互 (目标 NPC, 行动者名)。execute_action 的
        # talk/attack/help 对目标 NPC observe 后登记进来, step_autonomous 统一
        # 消费 (跑关系反思), 步末清空。让自治世界的社交动作进 NPC 记忆/信任/反思层。
        self._step_social: list[tuple["NPC", str]] = []
        # 结构化视觉事件缓冲 (单一事实源): execute_action / world_event 追加,
        # step_autonomous 每步执行前重置。前端回放读它 (序列化为 visual_events),
        # 不再解析中文事件串。旧调用方忽略本字段不受影响。
        self.visual_events: list[VisualEvent] = []
        # 世界层动作效果钩子: {action: [fn(world, agent, target, action, ve), ...]}。
        # 引擎只负责动作空间+物理规则 (移动/伤害/历史/视觉事件), "这个动作在本世界
        # 还引发什么" (理由生成/锻刀/世界事件等具体世界行为) 全部由世界层经此注入,
        # 引擎不硬编码任何具体世界的行为。默认空 = 纯物理引擎, 行为不变。
        self.action_effects: dict[str, list] = {}
        if path is not None:
            self._open(path)

    # ------------------------------------------------------------- 实体注册
    def add_entity(self, entity: Entity) -> None:
        self.entities[entity.name] = entity

    def get(self, name: str) -> Entity | None:
        return self.entities.get(name)

    def add_npc(self, name: str, persona_traits: dict[str, float], llm,
                embedder=None, data_dir: str = "data",
                location: str | None = None,
                reflection_threshold: float | None = None) -> "NPC":
        """创建或加载一个持久化 NPC (复用 NPC.create, 一 NPC 一库) 并登记入世界。

        location 缺省时放到第一个区域。NPC 认知对象与位置实体分开持有:
        _npcs 管认知, entities 管位置 (感知/档位调度用)。
        reflection_threshold: 透传给 NPC (重要性累积到多少触发自我反思);
        缺省用 NPC 默认 150。
        """
        from .npc import NPC   # 函数级导入, 避免模块加载期循环依赖
        kwargs = {} if reflection_threshold is None else \
            {"reflection_threshold": reflection_threshold}
        npc = NPC.create(name, persona_traits, llm=llm, embedder=embedder,
                         data_dir=data_dir, **kwargs)
        self._npcs[name] = npc
        self._npc_data_dirs[name] = data_dir   # 记录其独立 db 位置, 供世界持久化恢复
        loc = self.locations[location] if location else next(iter(self.locations.values()))
        self.add_entity(Entity("npc", name, loc))
        return npc

    def add_player(self, name: str, location: str) -> Player:
        """登记一个玩家实体到某区域。"""
        player = Player(name, self.locations[location])
        self.add_entity(player)
        return player

    def npc(self, name: str) -> "NPC | None":
        return self._npcs.get(name)

    # ------------------------------------------------------------- 空间感知
    def perceive(self, npc_name: str, now: float,
                 radius: float | None = None) -> list[int]:
        """空间感知: NPC 感知视距内的玩家, 生成自然语言观察喂 npc.observe()。

        替代手写 observe(): 玩家走进 NPC 视距 → NPC 自然"看到"并记下。
        粒度随认知档位: full=富细节 (玩家+位置+与NPC的接近), compressed=稀疏
        (仅在场), idle=不感知。视距外 (distance > radius) 感知不到。
        重复感知同一在场走既有观察去重 (0.92 合并), 不灌水。返回观察 id 列表。
        """
        npc = self._npcs.get(npc_name)
        if npc is None or npc._tier == "idle":
            return []
        me = self.entities[npc_name]
        r = self.perception_radius if radius is None else radius
        ids: list[int] = []
        for ent in self.entities.values():
            if ent.kind != "player" or distance(me, ent) > r:
                continue   # 非玩家或视距外
            if npc._tier == "full":
                content = f"{ent.name} 出现在 {me.location.name}, 靠近 {npc_name}"
            else:   # compressed
                content = f"{ent.name} 在 {me.location.name}"
            ids.append(npc.observe(content, now, player_id=ent.name))
        # S2 社交在场感知 (缺省关): NPC 感知视距内其他 NPC 的**出现**。
        # 过渡驱动而非逐步重放: 只对新进入视距的 NPC 产生观察 (重复在场不重复
        # 入库, 0.92 去重仍是兜底); 离开视距即移出 seen, 重现会再触发。
        # 档位同玩家感知: full=富细节, compressed=仅在场, idle 经入口早退无感知。
        # 新观察同时登记 _step_social —— 关系反思走 E16 的 flush_social 路径
        # (full 档且新观察才反思, 幂等/异常安全), 信任度随之惰性更新。
        if self._social_perception:
            seen = self._social_seen.setdefault(npc_name, set())
            current: set[str] = set()
            for ent in self.entities.values():
                if (ent.kind != "npc" or ent is me or ent.dead
                        or distance(me, ent) > r):
                    continue
                current.add(ent.name)
            for other in sorted(current - seen):
                if npc._tier == "full":
                    content = f"{other} 出现在 {me.location.name}, 靠近 {npc_name}"
                else:   # compressed
                    content = f"{other} 在 {me.location.name}"
                ids.append(npc.observe(content, now, player_id=other))
                self._step_social.append((npc, other))
            # 就地更新 seen 为当前在场集合 (不能 seen &= current: 首步 seen 为空,
            # 交集恒空, 出现集合记不住, 每步都当"新出现")。离开者自然移出, 重现再触发。
            seen.clear()
            seen.update(current)
        return ids

    def player_action(self, player_name: str, action: str, target_npc: str,
                      now: float) -> int:
        """玩家对目标 NPC 做一个动作, 目标 NPC 自己观察并生成观察。

        action 是原始动作 (动词+对象, 如"帮藏眼"/"委托打造武器")。目标 NPC
        结合自己的记忆用 LLM 把动作观察成第三人称描述 (自生成), 再记录。
        脚本只管"玩家做了什么动作", 不管"NPC 怎么描述这件事"。返回观察 id。
        """
        npc = self._npcs.get(target_npc)
        if npc is None:
            raise KeyError(f"NPC '{target_npc}' 未注册入世界")
        self.advance(now)
        return npc.perceive_action(player_name, action, now)

    # ------------------------------------------------------------- 多智能体自治
    def add_agent_player(self, name: str, location: str, goal: str, llm,
                         persona_traits: dict[str, float] | None = None,
                         health: int = 100, attack: int = 10,
                         defense: int = 0) -> Player:
        """注册一个 LLM 驱动的玩家 Agent (有 goal, 自治决策)。"""
        player = Player(name, self.locations[location], goal=goal,
                        health=health, attack=attack, defense=defense)
        self.add_entity(player)
        self._agent_llms[name] = llm
        self._agent_personas[name] = persona_traits or {}
        return player

    def agent_perception(self, agent: Entity) -> str:
        """构建 agent 的感知视图 (非全知): 视距内存活实体 + 其血量/位置。"""
        visible = []
        for other in self.entities.values():
            if other is agent or other.dead:
                continue
            if distance(agent, other) <= self.perception_radius:
                visible.append(f"{other.name}(血{other.health},在{other.location.name})")
        return "; ".join(visible) if visible else "(空无一人)"

    def agent_state(self, agent: Entity) -> str:
        locs = "/".join(self.locations.keys())
        s = (f"血{agent.health}, 攻{agent.attack}, 防{agent.defense}, "
             f"在{agent.location.name} (可选区域: {locs})")
        if agent.reasons:   # 已积累的理由 (让 agent 知道已做什么、别重复)
            s += " | 已积累的理由: " + " / ".join(agent.reasons)
        return s

    def decide_agent(self, agent: Entity, memory_context: str = "") -> dict:
        """agent 决策下一步: LLM 战略判断 (非全知, 只看自己感知+记忆+目标)。

        R1: 对 NPC agent, 把对视距内、有关系记忆 (观察/反思) 的实体的信任度显式
        拼进 perception 喂给 decide_action。信任已由 talk/attack/help 更新 (E16),
        但决策接口此前只能靠 LLM 从记忆文本猜信任, 无因果接线 —— 现在信任值直接
        进决策输入, 稳定区分"可信/不可信"的交互对象。无関係记忆的不列 (避免陌生
        人 trust 0 灌水)。不改 decide_action 方法签名, 信任随上下文文本进输入。
        """
        llm = self._agent_llms.get(agent.name)
        if llm is None:
            return {"action": "wait", "reason": "无 LLM"}
        perception = self.agent_perception(agent)
        if memory_context:
            perception += " | 自己的记忆: " + memory_context
        npc = self._npcs.get(agent.name)
        if npc is not None:
            trust_bits: list[str] = []
            for other in self.entities.values():
                if other is agent or other.dead:
                    continue
                if distance(agent, other) > self.perception_radius:
                    continue   # 视距外
                if not npc.store.all_valid(player_id=other.name):
                    continue   # 无关系记忆, 不列 (陌生人 trust 0 无信息量)
                trust = npc.decider.relationship_trust(other.name)
                trust_bits.append(f"{other.name} {trust:+.2f}")
            if trust_bits:
                perception += " | 对视距内对象的信任度: " + ", ".join(trust_bits)
            # M3 身份信念注入 (缺省关): 身份信念是跨玩家泛化的自我认知
            # (type=identity, 共享流), 进决策上下文 —— 影响 NPC 对一切来往者的
            # 行为基调。只取最新一条 (身份是稳定的, 旧的被新泛化取代)。
            if self._use_identity_beliefs:
                ident = npc.store.all_valid(shared=True, types=["identity"])
                if ident:
                    perception += " | 身份信念: " + ident[-1].content
        return llm.decide_action(agent.name, agent.goal,
                                 self._agent_personas.get(agent.name, {}),
                                 perception, agent.history, self.agent_state(agent))

    def _observe_target_social(self, target: Entity, agent: Entity,
                               action_desc: str) -> "NPC | None":
        """E16: 社交动作 (talk/attack/help) 作用于 NPC 时, 目标 NPC 在自己的记忆流
        observe 这件事 (关系观察, player_id = 行动者名), 并把 (目标 NPC, 行动者)
        登记进 _step_social 供 step_autonomous 统一跑关系反思。返回目标 NPC
        (目标不是 NPC 则 None)。信任度随之惰性更新 (新观察改变关系记忆签名)。"""
        npc = self._npcs.get(target.name)
        if npc is None:
            return None
        npc.perceive_action(agent.name, action_desc, self.clock)
        self._step_social.append((npc, agent.name))
        return npc

    def _spread_rumor(self, speaker: Entity, listener: Entity, line: str) -> None:
        """S4 谣言传播 (缺省关): 两条路径, 都只产生传闻观察 (hearsay=True)。

        (1) 听见: 对话发生区域内、除说话者与对话者外的存活 NPC 听到这句话 ——
            观察进"说话者"的关系流 (player_id=说话者: 这是"他说了什么"的认知),
            hop=1。第三方不关心对话者是谁, 只关心谁说了话。
        (2) 转述: 说话者若是 NPC 且持有未封顶 (hop < HEARSAY_MAX_HOP) 的传闻记忆,
            把它转述给对话者 —— 对话者收到同内容、同说话者流、hop+1 的传闻。
            这就是"听说听说听说"的链: 每经一个 NPC 之口 +1 跳, 3 跳封顶不再传。
            内容/说话者流相同 → 与已有传闻去重合并 (不升级 hop), 所以三角传回
            自己不会无限加跳。

        两条路径的观察都登记 _step_social, 听者/转述接收者会对说话者跑关系反思
        (复用 E16 flush 路径, full 档且新观察才反思)。
        """
        # (1) 听见
        for name, npc in self._npcs.items():
            ent = self.entities.get(name)
            if ent is None or ent.dead or ent is speaker or ent is listener:
                continue
            if location_distance(speaker.location, ent) > self.perception_radius:
                continue
            npc.observe(f"{speaker.name} 说: {line}", self.clock,
                        player_id=speaker.name, hearsay=True, hop=1)
            self._step_social.append((npc, speaker.name))
        # (2) 转述
        speaker_npc = self._npcs.get(speaker.name)
        listener_npc = self._npcs.get(listener.name)
        if speaker_npc is None or listener_npc is None:
            return
        pending = [m for m in speaker_npc.store.all_valid(types=["observation"])
                   if m.hearsay and m.hop < HEARSAY_MAX_HOP]
        if not pending:
            return
        latest = max(pending, key=lambda m: (m.timestamp, m.id or 0))
        listener_npc.observe(latest.content, self.clock,
                             player_id=latest.player_id, hearsay=True,
                             hop=latest.hop + 1)
        self._step_social.append((listener_npc, latest.player_id or ""))

    @staticmethod
    def _norm_action(action) -> dict:
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

    def add_action_effect(self, action: str, fn) -> None:
        """注册世界层动作效果钩子 (引擎与世界行为解耦的扩展点)。

        引擎执行完 `action` 的通用语义后, 依次调用本动作注册的所有 fn,
        签名 fn(world, agent, target, action, ve)。fn 可改 agent (如 add_reason /
        attack) 和 ve (如 reason_added / weapon_attack), 把"这个动作在本世界还引发
        什么具体效果" (理由生成/锻刀/目击/世界事件) 留给世界层决定 —— 引擎不硬编码
        任何具体世界的行为。target 对 move/flee/wait 等无目标动作为 None。
        """
        self.action_effects.setdefault(action, []).append(fn)

    def _run_effects(self, action: str, agent: Entity, target: "Entity | None",
                     action_dict: dict, ve: VisualEvent) -> None:
        """依次执行本动作注册的所有世界层效果钩子 (无注册则什么都不做)。"""
        for eff in self.action_effects.get(action, []):
            eff(self, agent, target, action_dict, ve)

    # ----------------------------------------------------- S5 内生事件 (行为链)
    def add_chain_rule(self, action: str, threshold: int, description: str) -> None:
        """注册行为链规则 (S5 内生事件): 同一 actor 对同一 target 连续做出
        threshold 次同型动作 (链: 期间做任何别的带目标动作即断链清零), 触发
        世界事件 description (在 actor 所在区域, 触发后该链计数清零重新累积)。

        与 add_action_effect 同族: 引擎只计数与分派, "什么算链、触发什么事件"
        的语义由世界层注册 (如"搜查连空三次→署内问责")。缺省无规则 = 现行为。
        """
        self._chain_rules[action] = (threshold, description)

    def _chain_update(self, agent: Entity, action: str, target: Entity) -> None:
        """带目标动作执行后更新行为链计数; 达阈触发世界事件。

        断链语义: "连续同型动作"——同一 actor 的任何**别的**带目标动作 (哪怕
        该动作类型没有注册规则, 如 talk) 都会打断其余链。先无条件清掉非本键的
        计数, 再看本键有没有规则: 无规则的动作只断链不累积。
        """
        key = (action, target.name)
        counters = self._chain_counters.get(agent.name)
        if counters:
            for other in [k for k in counters if k != key]:
                del counters[other]   # 断链
        rule = self._chain_rules.get(action)
        if rule is None:
            return   # 无规则: 只断链, 不累积
        threshold, description = rule
        if counters is None:
            counters = self._chain_counters[agent.name] = {}
        counters[key] = counters.get(key, 0) + 1
        if counters[key] >= threshold:
            counters[key] = 0     # 触发后清零, 下一轮链重新累积
            self.world_event(description, self.clock, at=agent.location.name)

    def execute_action(self, agent: Entity, action: dict) -> str:
        """执行动作并应用影响, 返回发生了什么 (供打印/记录)。非全知: 只影响直接相关方。

        结构化视觉事件是单一事实源: 每个分支产出 VisualEvent 追加进
        self.visual_events, 返回的字符串由 ve.describe() 派生 (与旧实现逐字一致)。
        前端回放读 visual_events, 不再解析中文事件串。
        """
        action = self._norm_action(action)   # R7: 入口 schema 校验/降级
        a = action.get("action", "wait")
        target = self.get(action.get("target", "")) if action.get("target") else None
        # S5 行为链计数: 任何对存活目标的动作都过链检查 (无注册规则 = no-op,
        # 缺省行为不变)。放在分支前, talk/attack/help/hide 等一律覆盖。
        if target is not None and target.is_alive():
            self._chain_update(agent, a, target)

        def emit(ve: VisualEvent) -> str:
            """追加结构化事件并返回其派生字符串。"""
            self.visual_events.append(ve)
            return ve.describe()

        if a == "move":
            dest = action.get("dest") or agent.location.name
            if dest in self.locations:
                agent.move(self.locations[dest])
                agent.record(f"移动到 {dest}")
                return emit(VisualEvent("move", agent.name, self.clock,
                                        location=agent.location.name, to=dest))
            return emit(VisualEvent("move", agent.name, self.clock,
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
            if target.name in self._npcs:
                try:
                    npc = self._observe_target_social(target, agent, f"对TA说: {line}")
                    if npc is not None:
                        reply = npc.speak(agent.name, line, self.clock) or ""
                except Exception:
                    return emit(VisualEvent(
                        "conversation", agent.name, self.clock,
                        location=agent.location.name, target=target.name,
                        utterance=line, success=False,
                        failure_reason="认知事件生成失败"))
            agent.record(f"对 {target.name} 说: {line}")
            target.record(f"{agent.name} 对TA说: {line}")
            # S4 谣言传播 (缺省关): 这句话被范围内第三方听到 + 说话者 NPC 可能
            # 把持有的传闻转述给对话者。关时零行为。
            if self._rumor_spread and line:
                self._spread_rumor(agent, target, line)
            ve = VisualEvent("conversation", agent.name, self.clock,
                             location=agent.location.name, target=target.name,
                             utterance=line, reply=reply, reply_speaker=target.name)
            # 世界层效果 (理由生成/锻刀等具体世界行为) 由情境经钩子注入, 引擎不再硬编码。
            self._run_effects("talk", agent, target, action, ve)
            return emit(ve)
        if a == "attack" and target and target.is_alive():
            dmg = max(0, agent.attack - target.defense + random.randint(-2, 2))
            will_die = target.health - dmg <= 0   # 预判死亡 (提交后 target.dead 才定)
            # R6: 原子性 —— 可失败的认知事件生成在前, 成功才提交物理状态+历史。
            # 目标 NPC 先 observe (LLM/embedding 可能失败), 成功才扣血, 避免"血已扣
            # 但 NPC 没观察到、反思队列没登记"的撕裂。失败则中止 (不扣血/不记历史)。
            # 挨打的"反应"由目标下一步 decide_agent 行动承担 (逃跑/反击), 不在此回话。
            if target.name in self._npcs:
                try:
                    self._observe_target_social(
                        target, agent,
                        f"攻击了TA, 造成 {dmg} 伤害" + ("(致TA阵亡)" if will_die else ""))
                except Exception:
                    return emit(VisualEvent(
                        "attack", agent.name, self.clock,
                        location=agent.location.name, target=target.name,
                        success=False, failure_reason="认知事件生成失败"))
            # 认知事件生成成功 (或目标非 NPC) → 提交物理状态 + 历史
            target.take_damage(dmg)
            agent.record(f"攻击 {target.name}, 造成 {dmg} 伤害")
            target.record(f"{agent.name} 攻击了TA, 受到 {dmg} 伤害")
            ve = VisualEvent("attack", agent.name, self.clock,
                             location=agent.location.name, target=target.name,
                             damage=dmg, target_dead=target.dead)
            # 世界层效果 (如"执行官收缴持眼者→目击者得理由") 由情境经钩子注入。
            self._run_effects("attack", agent, target, action, ve)
            return emit(ve)
        if a == "flee":
            # 逃到离最近威胁最远的区域
            threats = [o for o in self.entities.values()
                       if o is not agent and not o.dead
                       and distance(agent, o) <= self.perception_radius]
            if threats:
                def farthest(loc: Location) -> float:
                    return min(((loc.x - t.location.x) ** 2 +
                                (loc.y - t.location.y) ** 2) ** 0.5
                               for t in threats)
                best = max(self.locations.values(), key=farthest)
                agent.move(best)
                agent.record(f"逃离威胁, 逃到 {best.name}")
                return emit(VisualEvent("flee", agent.name, self.clock,
                                        location=agent.location.name, to=best.name))
            return emit(VisualEvent("flee", agent.name, self.clock,
                                    location=agent.location.name, success=False,
                                    failure_reason="无威胁可逃"))
        if a in ("help", "hide") and target and target.is_alive():
            agent.record(f"{'帮助' if a == 'help' else '替'} {target.name}")
            target.record(f"{agent.name} {'帮了TA' if a == 'help' else '替TA藏匿'}")
            ve = VisualEvent(a, agent.name, self.clock,
                             location=agent.location.name, target=target.name)
            # E16: 目标 NPC 观察这次帮助/藏匿进自己记忆流 (关系观察, 信任度随之
            # 惰性上升)。NPC 的"反应"同样由其下一步 decide_agent 行动承担。
            self._observe_target_social(
                target, agent, "帮助了TA" if a == "help" else "替TA藏匿")
            # 世界层效果 (如"帮持眼者→得理由") 由情境经钩子注入。
            self._run_effects(a, agent, target, action, ve)
            return emit(ve)
        agent.record("观望")
        return emit(VisualEvent("wait", agent.name, self.clock,
                                location=agent.location.name))

    def step_autonomous(self, now: float) -> tuple[list[str], dict[str, dict]]:
        """多智能体自治一步: 所有存活 agent 先决策 (同一时刻感知) → 统一执行 →
        重感知。NPC 额外走反思/计划。返回 (本步发生的事, 各 agent 的决策)。

        先决策后执行: 所有 agent 基于同一时刻的感知做决定, 再统一执行, 避免
        顺序偏差 (先行动的占便宜)。死亡即时生效。返回决策供调用方精确判断
        (如'旅行者本步是否对将军 talk'), 而非匹配历史文本。
        """
        self.advance(now)
        self.schedule_tiers(now)
        # 每天早晨自动规划 (复用 step 的逻辑)
        day = int(self.clock // 24)
        if day != self._last_plan_day and self.clock % 24 >= 7.0:
            for name, npc in self._npcs.items():
                if self.entities[name].dead:
                    continue   # 死去的 NPC 不再规划 (生命止于死亡那一刻)
                npc.generate_daily_plan(previous_day=f"第{day}天",
                                        date=f"第{day+1}天", now=self.clock)
            self._last_plan_day = day
        self._maybe_consolidate(now, day)   # M1 夜间固化 (缺省关 = no-op)
        # 1. 所有存活 agent 先决策 (基于同一时刻感知)
        decisions: dict[str, dict] = {}
        for name, agent in self.entities.items():
            if not agent.is_alive():
                continue
            memory_context = ""
            if name in self._npcs:   # NPC 用自己的记忆流做非全知上下文
                npc = self._npcs[name]
                mems = [m.content for m in npc.store.all_valid()[-5:]]
                memory_context = " | ".join(mems)
                # 档位决策门控 (消融开关, 缺省关): idle NPC 规则等待, 零 LLM。
                if self._decision_tier_gate and npc._tier == "idle":
                    decisions[name] = {"action": "wait", "target": "",
                                       "utterance": "", "dest": "",
                                       "reason": "idle 档: 视距内无玩家, 规则等待"}
                    continue
            decisions[name] = self.decide_agent(agent, memory_context)
        # 2. 统一执行 (应用影响)。重置结构化视觉事件缓冲 —— 本步 execute_action
        # 追加的事件执行后恰好等于 self.visual_events, 供回放层读取。
        self.visual_events = []
        events: list[str] = []
        for name, agent in self.entities.items():
            if not agent.is_alive():
                continue
            outcome = self.execute_action(agent, decisions[name])
            events.append(outcome)
            # M5: 重大状态变化 (战斗/逃跑/帮匿) 打断当日计划 → 从当前时刻重规划。
            # 模拟里此前只有每天早晨一次日计划, 计划整天静止 (被打了还在按计划
            # "打铁"), 对话检索会引用与事实矛盾的旧计划。talk/move/wait 不打断
            # 日程, 不重规划。重规划继承 H4: 旧计划失效 + 新块锚定当前时刻。
            # "想 XX" 的未发生结果 (目标已死/无威胁可逃) 状态没变, 也不重规划。
            a = decisions[name].get("action", "wait")
            happened = outcome not in (f"{agent.name} 观望",
                                       f"{agent.name} 想逃但无威胁")
            if a in self.INTERRUPT_ACTIONS and happened:
                npc = self._npcs.get(name)
                if npc:
                    npc.replan(now=self.clock, interruption=outcome)
            # 挨打方 (未死) 的一天同样被打断 → 也重规划
            if a in ("attack", "counterattack"):
                tname = decisions[name].get("target", "")
                t_npc = self._npcs.get(tname) if tname else None
                if t_npc and self.entities.get(tname) is not None \
                        and self.entities[tname].is_alive():
                    t_npc.replan(now=self.clock,
                                 interruption=f"被 {agent.name} 攻击了")
        # 3. 重感知 (行动改变了谁在哪/谁死了) + NPC 反思
        for name, npc in self._npcs.items():
            if self.entities[name].dead:
                continue
            self.perceive(name, now)
            if npc._tier != "idle":
                npc.maybe_reflect_self(now)
        # 4. E16/R4/R5: 社交交互过关系反思层 —— 消费 _step_social (flush_social
        # 带 try/finally, 异常也清空不重复处理)。信任度随之惰性更新, 参与后续判定。
        self.flush_social(now)
        if self._conn is not None:
            self.save()
        return events, decisions

    def _maybe_consolidate(self, now: float, day: int) -> None:
        """M1 夜间固化 (缺省关): 到达 consolidate_hour 且该天未固化过时, 对每个
        存活 NPC 跑 consolidate (当天观察 → episode, 幂等)。与早晨日计划同族:
        同一天只触发一次, 死亡检查同计划波。"""
        if not self._consolidation:
            return
        if day == self._last_consolidate_day:
            return
        if self.clock % 24 < self._consolidate_hour:
            return
        for name, npc in self._npcs.items():
            if self.entities[name].dead:
                continue   # 死去的 NPC 不再固化 (生命止于死亡那一刻)
            npc.consolidate(self.clock)
        self._last_consolidate_day = day

    def flush_social(self, now: float) -> None:
        """消费本步社交交互 (_step_social), 对目标 NPC 跑关系反思 (E16)。

        R4: 外层 try/finally —— 即便 reflect_relationship 抛异常 (LLM/DB 失败),
        也必清空 _step_social, 下步不重复处理旧社交事件 (重复反思 + 重复 LLM 调用)。
        内层 try/except —— 单次交互的反思失败不阻塞其余交互。
        R5: 对外暴露 —— 只调 execute_action 不推进自治步的调用方, 可显式 flush 触发
        关系反思, 契约明确 (不靠"之后恰好调 step_autonomous"才反思)。

        门控同 speak: 仅 full 档且出现新观察才重跑, 避免反思无限增殖/信任漂移。
        talk 已在 execute_action 里经 speak 反思过, 此处再跑被 _reflected_obs 门控
        拦下 (幂等); attack/help 没走 speak, 靠这里补上关系反思。
        """
        try:
            for npc, actor in self._step_social:
                try:
                    if self.entities[npc.name].dead or npc._tier != "full":
                        continue
                    obs_count = len(npc.store.all_valid(player_id=actor,
                                                        types=["observation"]))
                    if obs_count > npc._reflected_obs.get(actor, 0):
                        npc.reflect_relationship(actor, now)
                        npc._reflected_obs[actor] = obs_count
                except Exception:
                    continue   # 单次交互反思失败不阻塞其余 (R4)
        finally:
            self._step_social.clear()   # R4: 异常也清空, 不留下步重复处理

    # ------------------------------------------------------------- 距离调度
    def tier_of(self, npc_name: str) -> str:
        """距离调度: 按 NPC 到最近玩家的距离推导认知档位 (替代手动 set_tier)。

        - 玩家同区域 (distance <= full_radius)   → full   (近处全认知)
        - 玩家在视距内 (distance <= 视距)         → compressed (远处压缩认知)
        - 无玩家在视距内 / 世界无玩家              → idle   (空闲省认知)
        这是 blog「问题一」的落地: 认知开销随距离自动降档。
        """
        me = self.entities[npc_name]
        nearest: float | None = None
        for ent in self.entities.values():
            if ent.kind != "player":
                continue
            d = distance(me, ent)
            if nearest is None or d < nearest:
                nearest = d
        if nearest is None:
            return "idle"
        if nearest <= self.full_radius:
            return "full"
        if nearest <= self.perception_radius:
            return "compressed"
        return "idle"

    def schedule_tiers(self, now: float) -> dict[str, str]:
        """按距离给所有 NPC 自动设档, 返回 {npc: 档位}。step (阶段5) 每步调用。"""
        result: dict[str, str] = {}
        for name in self._npcs:
            tier = "full" if self._force_full_tier else self.tier_of(name)
            self._npcs[name].set_tier(tier)
            result[name] = tier
        self.advance(now)
        return result

    # ------------------------------------------------------------- 世界事件
    def world_event(self, desc: str, now: float,
                    at: str | None = None,
                    radius: float | None = None) -> dict[str, list[int]]:
        """世界事件: 共享事件, 范围内 NPC 作为世界观察 (不带 player_id) 感知。

        at: 事件发生的区域名; None = 全图事件 (影响所有 NPC)。
        radius: 影响半径 (缺省用视距)。返回 {npc: [观察id]}。
        感知走 npc.observe() (世界观察不带 player_id), 重要性累积仍受档位门控
        (idle 记录但不反思), 后续走降权遗忘。事件观察是环境性的, 不归属任何玩家。
        """
        if at is None:
            targets = list(self._npcs.keys())
        else:
            center = self.locations[at]
            r = self.perception_radius if radius is None else radius
            targets = [n for n in self._npcs
                       if location_distance(center, self.entities[n]) <= r]
        result: dict[str, list[int]] = {}
        for name in targets:
            if self.entities[name].dead:
                continue   # L7: 死去的 NPC 不感知世界事件 (同 step/日计划的死亡检查)
            result[name] = [self._npcs[name].observe(desc, now)]
        # 结构化视觉事件 (回放层用): 世界事件不归属任何玩家, actor 记"世界"。
        # 即使范围内无 NPC 也记录 —— 它是环境状态, 与谁感知到无关。
        self.visual_events.append(
            VisualEvent("world_event", "世界", now,
                        location=at or "", description=desc))
        self.advance(now)
        return result

    # ------------------------------------------------------------- 模拟驱动
    def step(self, now: float) -> dict:
        """推进一个模拟步: 时钟→距离调度→空间感知→按档自我反思→遗忘→持久化。

        - 距离调度: 按最近玩家距离给每个 NPC 自动设档 (近处全认知/远处省认知)。
        - 空间感知: 每个 NPC 感知视距内玩家, 生成观察 (idle 不感知)。
        - 按档反思: full/compressed 的 NPC 在重要性累积超阈值时自我反思;
          idle 只记录不反思。关系反思由 speak (玩家对话) 触发, 不在此。
        - 遗忘: observe/advance 已按 SWEEP_INTERVAL 自动清扫 (降权不删除)。
        - 持久化: 世界状态自动落库 (仅持久化世界)。
        返回 {clock, tiers, new_observations}。
        """
        self.advance(now)
        tiers = self.schedule_tiers(now)
        # 每天早晨 (新的一天且已过 07:00): 全体 NPC 在世界背景下生成当日计划
        day = int(self.clock // 24)
        if day != self._last_plan_day and self.clock % 24 >= 7.0:
            for name, npc in self._npcs.items():
                if self.entities[name].dead:
                    continue   # 死去的 NPC 不再规划 (同 step_autonomous)
                npc.generate_daily_plan(previous_day=f"第{day}天",
                                        date=f"第{day+1}天", now=self.clock)
            self._last_plan_day = day
        self._maybe_consolidate(now, day)   # M1 夜间固化 (缺省关 = no-op)
        new_obs: dict[str, int] = {}
        for name, npc in self._npcs.items():
            ids = self.perceive(name, now)
            if ids:
                new_obs[name] = len(ids)
            if npc._tier != "idle":
                npc.maybe_reflect_self(now)   # 重要性超阈值才反思 (内部门控)
        if self._conn is not None:
            self.save()
        return {"clock": self.clock, "tiers": tiers, "new_observations": new_obs}

    # ------------------------------------------------------------- 移动与时钟
    def move(self, name: str, location_name: str, now: float) -> None:
        """把实体移到某区域, 并推进时钟。"""
        self.entities[name].move(self.locations[location_name])
        self.advance(now)

    def advance(self, now: float) -> None:
        """推进游戏时钟 (取 max, 容忍乱序事件)。"""
        if now > self.clock:
            self.clock = now

    # ------------------------------------------------------------- 持久化
    def _open(self, path: str) -> None:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS entity ("
            "name TEXT PRIMARY KEY, kind TEXT, location TEXT, x REAL, y REAL,"
            " health INTEGER DEFAULT 100, attack INTEGER DEFAULT 10,"
            " defense INTEGER DEFAULT 0, goal TEXT DEFAULT '',"
            " dead INTEGER DEFAULT 0, role TEXT DEFAULT '',"
            " history TEXT DEFAULT '[]', reasons TEXT DEFAULT '[]')")
        # 旧库迁移 (M9): M9 之前建的 world.db 只有 name/kind/location/x/y 五列,
        # 实体物理状态 (血/攻防/目标/死亡/角色/历史/理由) 从未落库, 恢复即全丢。
        # 按 Entity 默认值补列 —— 旧库本就没存过这些状态, 默认值是唯一合理兜底。
        cols = {r[1] for r in self._conn.execute("PRAGMA table_info(entity)")}
        for col, ddl in (
                ("health", "INTEGER DEFAULT 100"),
                ("attack", "INTEGER DEFAULT 10"),
                ("defense", "INTEGER DEFAULT 0"),
                ("goal", "TEXT DEFAULT ''"),
                ("dead", "INTEGER DEFAULT 0"),
                ("role", "TEXT DEFAULT ''"),
                ("history", "TEXT DEFAULT '[]'"),
                ("reasons", "TEXT DEFAULT '[]'")):
            if col not in cols:
                self._conn.execute(f"ALTER TABLE entity ADD COLUMN {col} {ddl}")
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)")

    def save(self) -> None:
        """把世界状态 (实体全量状态 + 时钟) 写入 world.db。

        实体不止位置: 血/攻防/目标/死亡/角色/历史/理由一并落库 (M9) ——
        跨进程恢复后将军的血量、旅行者的攻与已积累的理由、角色的特殊判定
        都不该丢, 否则自治弧线从一半重头再来。
        """
        if self._conn is None:
            raise RuntimeError("该世界是内存世界, 无法持久化 (构造时请传 path)")
        with self._lock, self._conn:
            self._conn.execute("DELETE FROM entity")
            for ent in self.entities.values():
                self._conn.execute(
                    "INSERT INTO entity (name, kind, location, x, y,"
                    " health, attack, defense, goal, dead, role, history,"
                    " reasons) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (ent.name, ent.kind, ent.location.name,
                     ent.location.x, ent.location.y,
                     ent.health, ent.attack, ent.defense, ent.goal,
                     1 if ent.dead else 0, ent.role,
                     json.dumps(ent.history), json.dumps(ent.reasons)))
            self._conn.execute(
                "INSERT OR REPLACE INTO meta (key, value) VALUES ('clock', ?)",
                (json.dumps(self.clock),))
            # NPC 注册表: {name: data_dir}, 供 load 恢复各 NPC 的记忆与面
            self._conn.execute(
                "INSERT OR REPLACE INTO meta (key, value) VALUES ('npcs', ?)",
                (json.dumps(self._npc_data_dirs),))

    def load(self, llm=None, embedder=None) -> None:
        """从 world.db 恢复世界状态 (实体全量状态 + 时钟 + NPC 注册表)。

        传入 llm/embedder 时, 同时按注册表重新实例化各 NPC (从各自独立 db
        恢复其全部记忆流与面)。不传则只恢复实体与位置时钟 (NPC 需另行 add_npc)。
        实体的血/攻防/目标/死亡/角色/历史/理由一并恢复 (M9), 跨进程续跑不失态。
        """
        if self._conn is None:
            raise RuntimeError("该世界是内存世界, 无法加载")
        with self._lock:
            for row in self._conn.execute(
                    "SELECT name, kind, location, x, y, health, attack, defense,"
                    " goal, dead, role, history, reasons FROM entity"):
                (name, kind, loc_name, x, y, health, attack, defense,
                 goal, dead, role, history, reasons) = row
                loc = self.locations.get(loc_name)
                if loc is None:   # 区域表漂移兜底: 按存下的坐标重建
                    loc = Location(loc_name, x, y)
                    self.locations[loc_name] = loc
                self.entities[name] = Entity(
                    kind=kind, name=name, location=loc,
                    health=health if health is not None else 100,
                    attack=attack if attack is not None else 10,
                    defense=defense if defense is not None else 0,
                    goal=goal or "", dead=bool(dead),
                    role=role or "",
                    history=json.loads(history) if history else [],
                    reasons=json.loads(reasons) if reasons else [])
            row = self._conn.execute(
                "SELECT value FROM meta WHERE key='clock'").fetchone()
            if row:
                self.clock = float(json.loads(row[0]))
            # 恢复 NPC: 按注册表从各自独立 db 重新加载 (记忆流 + 面全部恢复)
            row = self._conn.execute(
                "SELECT value FROM meta WHERE key='npcs'").fetchone()
            if row and llm is not None:
                from .npc import NPC   # 函数级导入, 避免循环依赖
                for name, data_dir in json.loads(row[0]).items():
                    npc = NPC.load(os.path.join(data_dir, f"{name}.db"),
                                   llm, embedder=embedder)
                    self._npcs[name] = npc
                    self._npc_data_dirs[name] = data_dir

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None
