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
                 full_radius: float = 0.5) -> None:
        self.name = name
        self.locations: dict[str, Location] = {loc.name: loc for loc in locations}
        self.entities: dict[str, Entity] = {}
        self._npcs: dict[str, "NPC"] = {}   # NPC 认知对象 (实体注册表的子集)
        self._npc_data_dirs: dict[str, str] = {}   # NPC → 其独立 db 的 data_dir (持久化注册表)
        self._agent_llms: dict[str, object] = {}   # agent → 其 LLM (决策用, 自治循环)
        self._agent_personas: dict[str, dict] = {}   # agent → 人格特质 (决策用)
        self.reason_cap = 3          # 一个 agent 最多积累几条理由 (说服用, world_auto_sim)
        self.weapon_gain = 4         # 与铁匠对话一次, 攻 +N (锻武器)
        self.weapon_cap = 24         # 攻的上限
        self.clock: float = 0.0            # 游戏内时间 (小时, 单调递增)
        self.perception_radius = perception_radius   # 视距: 玩家距 NPC 超过则感知不到
        self.full_radius = full_radius             # 同区域半径: 玩家距 NPC <= 此值 = full
        self.path = path
        self._conn: sqlite3.Connection | None = None
        self._lock = threading.RLock()
        self._last_plan_day = -1   # 已生成过日计划的天 (0-based); step 每天早晨自动规划
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
        """agent 决策下一步: LLM 战略判断 (非全知, 只看自己感知+记忆+目标)。"""
        llm = self._agent_llms.get(agent.name)
        if llm is None:
            return {"action": "wait", "reason": "无 LLM"}
        perception = self.agent_perception(agent)
        if memory_context:
            perception += " | 自己的记忆: " + memory_context
        return llm.decide_action(agent.name, agent.goal,
                                 self._agent_personas.get(agent.name, {}),
                                 perception, agent.history, self.agent_state(agent))

    def execute_action(self, agent: Entity, action: dict) -> str:
        """执行动作并应用影响, 返回发生了什么 (供打印/记录)。非全知: 只影响直接相关方。"""
        a = action.get("action", "wait")
        target = self.get(action.get("target", "")) if action.get("target") else None
        if a == "move":
            dest = action.get("dest") or agent.location.name
            if dest in self.locations:
                agent.move(self.locations[dest])
                agent.record(f"移动到 {dest}")
                return f"{agent.name} 移动到 {dest}"
            return f"{agent.name} 想移动到不存在的 {dest}, 未动"
        if a == "talk" and target and target.is_alive():
            line = action.get("utterance", "")
            agent.record(f"对 {target.name} 说: {line}")
            target.record(f"{agent.name} 对TA说: {line}")
            out = f"{agent.name} 对 {target.name} 说: {line}"
            # 理由 (仅玩家积累): 学者取证 / 医者证言 / 铁匠经济之弊
            if agent.kind == "player":
                if "scholar" in target.role:
                    r = "从小梅的孤本典籍中取证: 眼狩令令持眼者流离失所"
                elif "healer" in target.role:
                    r = "听桃音讲述眼狩令下持眼者被迫离散、伤者无依的苦"
                elif "blacksmith" in target.role:
                    r = "刚郎作证: 眼狩令收缴神之眼后持眼者离散, 武器生意断绝, 铁匠营生受损"
                else:
                    r = None
                if r and agent.add_reason(r, self.reason_cap):
                    out += f" [旅行者积累理由, 现{len(agent.reasons)}条]"
            # 铁匠: 对话 = 锻一把武器, 攻提升 (与理由独立, 玩家找铁匠既取证又锻刀)
            if "blacksmith" in target.role and agent.attack < self.weapon_cap:
                agent.attack = min(self.weapon_cap, agent.attack + self.weapon_gain)
                out += f" [刚郎锻好武器, {agent.name}攻升至{agent.attack}]"
            return out
        if a == "attack" and target and target.is_alive():
            dmg = max(0, agent.attack - target.defense + random.randint(-2, 2))
            target.take_damage(dmg)
            agent.record(f"攻击 {target.name}, 造成 {dmg} 伤害")
            target.record(f"{agent.name} 攻击了TA, 受到 {dmg} 伤害")
            extra = f" → {target.name} 阵亡!" if target.dead else ""
            out = f"{agent.name} 攻击 {target.name}, 造成 {dmg} 伤害{extra}"
            # 执行官收缴持眼者 → 同地点的目击玩家积累一条理由 (亲眼所见)
            if "enforcer" in agent.role and "vision_holder" in target.role:
                for witness in self.entities.values():
                    if (witness.kind == "player" and witness is not agent
                            and witness is not target and witness.is_alive()
                            and witness.location is target.location):
                        if witness.add_reason(
                                f"目睹执行官当众收缴 {target.name} 的神之眼, 其家破人亡",
                                self.reason_cap):
                            out += f" [旅行者目击搜捕, 积累理由现{len(witness.reasons)}条]"
            return out
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
                return f"{agent.name} 逃离威胁, 逃到 {best.name}"
            return f"{agent.name} 想逃但无威胁"
        if a in ("help", "hide") and target and target.is_alive():
            agent.record(f"{'帮助' if a == 'help' else '替'} {target.name}")
            target.record(f"{agent.name} {'帮了TA' if a == 'help' else '替TA藏匿'}")
            out = f"{agent.name} {'帮助' if a == 'help' else '替'} {target.name}"
            # 帮持眼者护住神之眼 = 一条反眼狩令的理由 (仅玩家积累)
            if a == "help" and agent.kind == "player" and "vision_holder" in target.role:
                if agent.add_reason(f"助 {target.name} 藏好神之眼, 令其免遭收缴",
                                    self.reason_cap):
                    out += f" [旅行者积累理由, 现{len(agent.reasons)}条]"
            return out
        agent.record("观望")
        return f"{agent.name} 观望"

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
            decisions[name] = self.decide_agent(agent, memory_context)
        # 2. 统一执行 (应用影响)
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
        if self._conn is not None:
            self.save()
        return events, decisions

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
            tier = self.tier_of(name)
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
            result[name] = [self._npcs[name].observe(desc, now)]
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
            "CREATE TABLE IF NOT EXISTS entity "
            "(name TEXT PRIMARY KEY, kind TEXT, location TEXT, x REAL, y REAL)")
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)")

    def save(self) -> None:
        """把世界状态 (实体位置 + 时钟) 写入 world.db。"""
        if self._conn is None:
            raise RuntimeError("该世界是内存世界, 无法持久化 (构造时请传 path)")
        with self._lock, self._conn:
            self._conn.execute("DELETE FROM entity")
            for ent in self.entities.values():
                self._conn.execute(
                    "INSERT INTO entity (name, kind, location, x, y) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (ent.name, ent.kind, ent.location.name,
                     ent.location.x, ent.location.y))
            self._conn.execute(
                "INSERT OR REPLACE INTO meta (key, value) VALUES ('clock', ?)",
                (json.dumps(self.clock),))
            # NPC 注册表: {name: data_dir}, 供 load 恢复各 NPC 的记忆与面
            self._conn.execute(
                "INSERT OR REPLACE INTO meta (key, value) VALUES ('npcs', ?)",
                (json.dumps(self._npc_data_dirs),))

    def load(self, llm=None, embedder=None) -> None:
        """从 world.db 恢复世界状态 (实体位置 + 时钟 + NPC 注册表)。

        传入 llm/embedder 时, 同时按注册表重新实例化各 NPC (从各自独立 db
        恢复其全部记忆流与面)。不传则只恢复位置与时钟 (NPC 需另行 add_npc)。
        """
        if self._conn is None:
            raise RuntimeError("该世界是内存世界, 无法加载")
        with self._lock:
            for name, kind, loc_name, x, y in self._conn.execute(
                    "SELECT name, kind, location, x, y FROM entity"):
                loc = self.locations.get(loc_name)
                if loc is None:   # 区域表漂移兜底: 按存下的坐标重建
                    loc = Location(loc_name, x, y)
                    self.locations[loc_name] = loc
                self.entities[name] = Entity(kind, name, loc)
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
