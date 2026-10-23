"""世界运行门面：组装实体、认知、动作和持久化。

实体与空间模型见 world_model，结构化事件契约见 events。
原有类型从本模块重新导出，保持调用方兼容。
"""

from __future__ import annotations

import os
import random

from .events import VisualEvent
from .world_store import WorldStore
from .world_model import Location, Entity, Player, distance, location_distance
from .memory import HEARSAY_MAX_HOP   # 传闻链上限 (S4); memory 不依赖 world, 无循环


# --------------------------------------------------------------------- 世界
class World:
    """游戏世界: 持有区域、实体注册表、游戏时钟。

    世界状态单独持久化在 world.db (实体位置 + 时钟), 与每个 NPC 的独立 db 分离。
    不传 path 则为内存世界 (不可持久化, 供离线骨架测试)。
    """

    # 打断当日计划、触发重规划的动作 (M5): 战斗/逃跑/帮匿都是"日程被打破"的
    # 重大状态变化。talk/move/wait 是日程内的日常行为, 不打断。
    INTERRUPT_ACTIONS = ("attack", "counterattack", "flee", "help", "hide")
    # 需要目标且必须在感知范围内的动作 (F3-3: 防 LLM 幻觉出视距外目标隔空交互)
    INTERACT_ACTIONS = ("talk", "attack", "help", "hide")

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
                 consolidate_hour: float = 23.0,
                 threat_filter=None,
                 player_perception_transition: bool = False) -> None:
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
        # F6-6: 引擎没有敌意模型, flee 默认把视距内所有活实体都当威胁 (旧行为);
        # 世界层可注入 threat_filter(agent, other)->bool 缩小威胁集。
        self.threat_filter = threat_filter
        # F6-11 (可选, 缺省关): 玩家感知改过渡驱动 —— 只在玩家新进入视距/
        # 换区域/档位变化时生成观察, 重复在场不再每步 observe+merge。
        self._player_perception_transition = player_perception_transition
        self._player_seen: dict[str, dict[str, tuple[str, str]]] = {}
        self.path = path
        self._storage: WorldStore | None = None
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
                reflection_threshold: float | None = None,
                autonomous: bool = False) -> "NPC":
        """创建或加载一个持久化 NPC (复用 NPC.create, 一 NPC 一库) 并登记入世界。

        location 缺省时放到第一个区域。NPC 认知对象与位置实体分开持有:
        _npcs 管认知, entities 管位置 (感知/档位调度用)。
        reflection_threshold: 透传给 NPC (重要性累积到多少触发自我反思);
        缺省用 NPC 默认 150。
        autonomous: 是否把该 NPC 注册为自治 agent (决定/动作循环会调用其 LLM)。
        缺省 False = 旧行为 (只作为认知 NPC, decide_agent 返回"无 LLM" wait);
        开启后等价于老的私有 `_agent_llms[name]=llm` 写法, 由公开 API 承担。
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
        if autonomous:
            self.register_agent(name, llm, npc.persona_traits)
        return npc

    def register_agent(self, name: str, llm, persona_traits: dict | None = None) -> None:
        """把已存在的 NPC 实体注册为自治 agent (公开 API)。

        `add_npc(..., autonomous=True)` 内部调用本方法; 已加载/手工构造的世界可
        用它补注册, 不必再碰私有 `_agent_llms`。persona_traits 缺省沿用 NPC 自己
        的, 避免调用方再传一份。
        """
        if name not in self.entities:
            raise KeyError(f"实体 '{name}' 未注册入世界")
        self._agent_llms[name] = llm
        npc = self._npcs.get(name)
        traits = persona_traits if persona_traits is not None else (
            npc.persona_traits if npc is not None else {})
        self._agent_personas[name] = dict(traits)

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
        if me.dead:
            return []   # 死去的 NPC 不再感知 (同 world_event/step 的死亡检查)
        r = self.perception_radius if radius is None else radius
        ids: list[int] = []
        transition = self._player_perception_transition
        seen = self._player_seen.setdefault(npc_name, {}) if transition else None
        current: set[str] = set()
        for ent in self.entities.values():
            if ent.kind != "player" or ent.dead or distance(me, ent) > r:
                continue   # 非玩家 / 死者 / 视距外
            if transition:
                current.add(ent.name)
                key = (ent.location.name, npc._tier)
                if seen.get(ent.name) == key:
                    continue   # F6-11: 过渡驱动, 同一在场状态不重复 observe
                seen[ent.name] = key
            if npc._tier == "full":
                content = f"{ent.name} 出现在 {me.location.name}, 靠近 {npc_name}"
            else:   # compressed
                content = f"{ent.name} 在 {me.location.name}"
            ids.append(npc.observe(content, now, player_id=ent.name))
        if transition:
            for pname in [n for n in seen if n not in current]:
                seen.pop(pname, None)   # 离开视距 → 重进时重新观察
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
        # F4-1: 只转述与当前话题相关的传闻。旧实现取"最新一条"无条件转述,
        # A 和 B 聊天气也会把 C 的谣言塞给 B。用检索的相关性下限筛候选。
        hits = speaker_npc.store.retrieve(
            query=line, now=self.clock, top_k=1, types=["observation"],
            hearsay_only=True, min_relevance=0.15, mark_accessed=False)
        if not hits:
            return
        latest = hits[0]
        if latest["hop"] >= HEARSAY_MAX_HOP:
            return   # 已封顶
        # 不把"听者自己转述出去的传闻"再传回给听者 (三角回环), 也不把关于
        # 听者本人的传闻说给听者。
        if latest["player_id"] == listener.name:
            return
        if latest["content"].startswith(f"{listener.name} 告诉我:"):
            return
        content = f"{speaker.name} 告诉我: {latest['content']}"
        listener_npc.observe(content, self.clock,
                             player_id=latest["player_id"], hearsay=True,
                             hop=latest["hop"] + 1)
        self._step_social.append((listener_npc, latest["player_id"] or speaker.name))

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

    def _within_reach(self, agent: Entity, target: Entity | None) -> bool:
        """动作目标是否在可交互范围内 (F3-3): 非自身、存活、视距内。

        非全知原则要在动作层兑现 —— decide_action 只看到视距内实体, 但模型
        可能幻觉出别处/已死的名字; 不在视距内的 target 一律中止动作, 不允许
        "隔空攻击/对话/帮助"。范围沿用 perception_radius (与 agent_perception
        一致)。
        """
        return (target is not None and target is not agent
                and target.is_alive()
                and distance(agent, target) <= self.perception_radius)

    def _emit_failure(self, action_type: str, agent: Entity,
                      target: Entity | None, target_name: str,
                      reason: str) -> str:
        """记录一个中止的交互动作 (结构化事件 + 派生字符串)。"""
        # talk 的成功事件类型是 "conversation"; 失败也沿用同一类型, 否则
        # describe() 会落到默认分支显示成"观望"。
        ve_type = "conversation" if action_type == "talk" else action_type
        ve = VisualEvent(ve_type, agent.name, self.clock,
                         location=agent.location.name,
                         target=(target.name if target is not None else target_name),
                         success=False, failure_reason=reason)
        self.visual_events.append(ve)
        return ve.describe()

    def execute_action(self, agent: Entity, action: dict) -> str:
        """执行动作并应用影响, 返回发生了什么 (供打印/记录)。非全知: 只影响直接相关方。

        结构化视觉事件是单一事实源: 每个分支产出 VisualEvent 追加进
        self.visual_events, 返回的字符串由 ve.describe() 派生 (与旧实现逐字一致)。
        前端回放读 visual_events, 不再解析中文事件串。
        """
        action = self._norm_action(action)   # R7: 入口 schema 校验/降级
        a = action.get("action", "wait")
        target = self.get(action.get("target", "")) if action.get("target") else None
        # F3-3: 目标在视距外/已死/不存在 → 动作中止, 不扣血/不写历史/不对话。
        if (a in self.INTERACT_ACTIONS and action.get("target")
                and not self._within_reach(agent, target)):
            return self._emit_failure(
                a, agent, target, action.get("target", ""), "不在可交互范围")
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
                        # 对方话语已经由 _observe_target_social/perceive_action
                        # 观察入库, speak 只补记自己的回复, 避免双写 incoming。
                        reply = npc.speak(agent.name, line, self.clock,
                                          record_utterance=False) or ""
                except Exception:
                    return emit(VisualEvent(
                        "conversation", agent.name, self.clock,
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
            if line and agent.name in self._npcs:
                try:
                    self._npcs[agent.name].observe(f"我对 {target.name} 说: {line}",
                                                   self.clock, player_id=target.name)
                except Exception:
                    pass
            # 回复回流: 说话者是 NPC 时, 把对方回复 observe 进自己记忆流 (player_id=目标)。
            # 闭合此前的非对称 —— 旧实现里回复只进回放事件, 说话者的后续决策看不到
            # 对方答了什么, NPC 间"对话"退化成各自基于自己记忆的一串独白 (LLM 靠
            # 脑补补出"我确认过了")。现在双方对称: 接收方记得说话者的话 (既有
            # perceive_action), 说话者也记得接收方的回复 (本行)。说话者是玩家 (无认知
            # 对象) 时跳过。best-effort: 回流 observe 失败不中止已成功的对话 (回复
            # 仍在回放事件里), 只丢这条记忆写入。
            if reply and agent.name in self._npcs:
                try:
                    self._npcs[agent.name].observe(f"{target.name} 说: {reply}",
                                                   self.clock, player_id=target.name)
                except Exception:
                    pass
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
            # F6-5: 行为链只在动作成功提交后计数 (失败/中止不推进)。
            self._chain_update(agent, a, target)
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
            # F6-5: 行为链只在攻击成功提交后计数。
            self._chain_update(agent, a, target)
            return emit(ve)
        if a == "flee":
            # 逃到离最近威胁最远的区域
            threats = [o for o in self.entities.values()
                       if o is not agent and not o.dead
                       and distance(agent, o) <= self.perception_radius
                       and (self.threat_filter is None
                            or self.threat_filter(agent, o))]
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
            # F3-4: 与 attack/talk 对齐 —— 可失败的认知事件在前, 成功才提交
            # history/effects; 失败中止动作, 不留"状态已改但 NPC 没观察到"。
            try:
                self._observe_target_social(
                    target, agent, "帮助了TA" if a == "help" else "替TA藏匿")
            except Exception:
                return self._emit_failure(
                    a, agent, target, target.name, "认知事件生成失败")
            agent.record(f"{'帮助' if a == 'help' else '替'} {target.name}")
            target.record(f"{agent.name} {'帮了TA' if a == 'help' else '替TA藏匿'}")
            ve = VisualEvent(a, agent.name, self.clock,
                             location=agent.location.name, target=target.name)
            # E16: 目标 NPC 观察这次帮助/藏匿进自己记忆流 (关系认知, 信任度随之
            # 惰性上升)。目标非 NPC 时 _observe_target_social 返回 None, 无认知事件。
            # 世界层效果 (如"帮持眼者→得理由") 由情境经钩子注入。
            self._run_effects(a, agent, target, action, ve)
            # F6-5: 行为链只在帮助/藏匿成功提交后计数。
            self._chain_update(agent, a, target)
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
                try:
                    npc.generate_daily_plan(previous_day=f"第{day}天",
                                            date=f"第{day+1}天", now=self.clock)
                except Exception:
                    continue   # 单个 NPC 规划失败不阻塞其余 (F3-5)
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
                # F1-6: 只取共享流 + 视距内实体的关系记忆。别的玩家的私有记忆
                # 不能进入本次决策上下文 (否则 B 会基于 A 的秘密做决定)。
                visible = {e.name for e in self.entities.values()
                           if e is not agent and not e.dead
                           and distance(agent, e) <= self.perception_radius}
                mems = [m.content for m in npc.store.all_valid()
                        if m.player_id is None or m.player_id in visible][-5:]
                memory_context = " | ".join(mems)
                # 档位决策门控 (消融开关, 缺省关): idle NPC 规则等待, 零 LLM。
                if self._decision_tier_gate and npc._tier == "idle":
                    decisions[name] = {"action": "wait", "target": "",
                                       "utterance": "", "dest": "",
                                       "reason": "idle 档: 视距内无玩家, 规则等待"}
                    continue
            try:
                decisions[name] = self.decide_agent(agent, memory_context)
            except Exception as e:
                # F3-5: 一个 agent 的 LLM/网络失败不能拖垮整步; 降级 wait,
                # 其余 agent 仍按同一时刻感知决策/执行。
                decisions[name] = {"action": "wait", "target": "",
                                   "utterance": "", "dest": "",
                                   "reason": f"决策异常: {e}"}
        # 2. 统一执行 (应用影响)。重置结构化视觉事件缓冲 —— 本步 execute_action
        # 追加的事件执行后恰好等于 self.visual_events, 供回放层读取。
        self.visual_events = []
        events: list[str] = []
        for name, agent in self.entities.items():
            if not agent.is_alive():
                continue
            try:
                outcome = self.execute_action(agent, decisions[name])
            except Exception as e:
                events.append(f"{agent.name} 动作异常: {e}")
                continue   # 动作失败不触发 replan, 其余 agent 继续
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
                    try:
                        npc.replan(now=self.clock, interruption=outcome)
                    except Exception:
                        pass   # 重规划失败不拖垮整步 (F3-5)
            # 挨打方 (未死) 的一天同样被打断 → 也重规划
            if a in ("attack", "counterattack"):
                tname = decisions[name].get("target", "")
                t_npc = self._npcs.get(tname) if tname else None
                if t_npc and self.entities.get(tname) is not None \
                        and self.entities[tname].is_alive():
                    try:
                        t_npc.replan(now=self.clock,
                                     interruption=f"被 {agent.name} 攻击了",
                                     interruption_player=agent.name)
                    except Exception:
                        pass   # 受害者重规划失败不拖垮整步 (F3-5)
        # 3. 重感知 (行动改变了谁在哪/谁死了) + NPC 反思
        for name, npc in self._npcs.items():
            if self.entities[name].dead:
                continue
            try:
                self.perceive(name, now)
            except Exception:
                pass   # 单个 NPC 感知失败不阻塞其余 (F3-5)
            try:
                if npc._tier != "idle":
                    npc.maybe_reflect_self(now)
            except Exception:
                pass
        # 4. E16/R4/R5: 社交交互过关系反思层 —— 消费 _step_social (flush_social
        # 带 try/finally, 异常也清空不重复处理)。信任度随之惰性更新, 参与后续判定。
        self.flush_social(now)
        if self._storage is not None:
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
            try:
                npc.consolidate(self.clock)
                # F4-4: 身份信念与夜间固化同一节拍触发; 仅开关打开时生成
                # (缺省关 = 现行为), 与 decide_agent 的 identity 注入同开关。
                if self._use_identity_beliefs:
                    npc.reflect_identity(self.clock)
            except Exception:
                continue   # 单个 NPC 固化/身份反思失败不阻塞其余 (F3-5)
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
        if me.dead:
            return "idle"   # 死去的 NPC 不参与认知调度
        nearest: float | None = None
        for ent in self.entities.values():
            if ent.kind != "player" or ent.dead:
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
        # F2-3: 同一事件文本对所有 NPC 的重要性相同 (player_id=None), 只打一次分
        # 复用; 旧实现每个 NPC 调一次 score_importance (N 个 NPC = N 次 LLM)。
        living = [n for n in targets if not self.entities[n].dead]
        importance: float | None = None
        if living:
            try:
                importance = self._npcs[living[0]].llm.score_importance(desc, None)
            except Exception:
                importance = None   # 打分失败则各 NPC 自行兜底 (per-NPC try 仍在)
        result: dict[str, list[int]] = {}
        for name in targets:
            if self.entities[name].dead:
                continue   # L7: 死去的 NPC 不感知世界事件 (同 step/日计划的死亡检查)
            try:
                result[name] = [self._npcs[name].observe(
                    desc, now, importance=importance)]
            except Exception:
                continue   # 单个 NPC 感知世界事件失败不阻塞其余 (F3-5)
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
        返回 {clock, tiers, new_observations}; new_observations 是**净新增**
        观察数 (merge 的重复观察不计入, 见 F6-4)。
        """
        self.advance(now)
        tiers = self.schedule_tiers(now)
        # 每天早晨 (新的一天且已过 07:00): 全体 NPC 在世界背景下生成当日计划
        day = int(self.clock // 24)
        if day != self._last_plan_day and self.clock % 24 >= 7.0:
            for name, npc in self._npcs.items():
                if self.entities[name].dead:
                    continue   # 死去的 NPC 不再规划 (同 step_autonomous)
                try:
                    npc.generate_daily_plan(previous_day=f"第{day}天",
                                            date=f"第{day+1}天", now=self.clock)
                except Exception:
                    continue   # 单个 NPC 规划失败不阻塞其余 (F3-5)
            self._last_plan_day = day
        self._maybe_consolidate(now, day)   # M1 夜间固化 (缺省关 = no-op)
        new_obs: dict[str, int] = {}
        for name, npc in self._npcs.items():
            if self.entities[name].dead:
                continue   # 死去的 NPC 不再感知/反思 (同 step_autonomous)
            before = npc.memory_count()
            try:
                self.perceive(name, now)
            except Exception:
                pass   # 单个 NPC 感知失败不阻塞其余 (F3-5)
            # F6-4: 只统计**净新增**记忆, merge 的重复观察不算 new_observations。
            added = npc.memory_count() - before
            if added > 0:
                new_obs[name] = added
            try:
                if npc._tier != "idle":
                    npc.maybe_reflect_self(now)   # 重要性超阈值才反思 (内部门控)
            except Exception:
                pass
        # F3-2: step 也必须消费社交交互队列 —— social_perception 在 perceive 里
        # 登记 _step_social, 此前只有 step_autonomous 调 flush_social, 导致
        # step 驱动时队列跨步积压且关系反思永不跑。
        self.flush_social(now)
        if self._storage is not None:
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
        self._storage = WorldStore(path)

    def save(self) -> None:
        """保存世界快照，并在世界库提交前尽力保存各 NPC 独立库。"""
        if self._storage is None:
            raise RuntimeError("该世界是内存世界, 无法持久化 (构造时请传 path)")
        metadata = {
            "clock": self.clock,
            "npcs": self._npc_data_dirs,
            "agent_npcs": sorted(n for n in self._agent_llms if n in self._npcs),
            "last_plan_day": self._last_plan_day,
            "last_consolidate_day": self._last_consolidate_day,
        }
        with self._storage.write_snapshot(self.entities.values(), metadata):
            for npc in self._npcs.values():
                try:
                    npc.save()
                except Exception:
                    continue

    def load(self, llm=None, embedder=None, agent_llms: dict | None = None) -> None:
        """恢复世界状态；提供 llm 时恢复 NPC 认知与自治注册。

        区域配置和运行依赖由调用方提供。agent_llms 可为各自治 NPC 重新绑定
        独立模型实例，未指定者使用统一 llm；模型对象不存入数据库。
        """
        if self._storage is None:
            raise RuntimeError("该世界是内存世界, 无法加载")
        with self._storage.read_snapshot() as snapshot:
            for ent in snapshot.entities:
                loc = self.locations.get(ent.location.name)
                if loc is None:
                    loc = ent.location
                    self.locations[loc.name] = loc
                ent.location = loc
                self.entities[ent.name] = ent
            meta = snapshot.metadata
            if "clock" in meta:
                self.clock = float(meta["clock"])
            self._last_plan_day = int(meta.get("last_plan_day", -1))
            self._last_consolidate_day = int(meta.get("last_consolidate_day", -1))
            if "npcs" in meta and llm is not None:
                from .npc import NPC
                for name, data_dir in meta["npcs"].items():
                    npc = NPC.load(os.path.join(data_dir, f"{name}.db"),
                                   llm, embedder=embedder)
                    self._npcs[name] = npc
                    self._npc_data_dirs[name] = data_dir
            if "agent_npcs" in meta and llm is not None:
                for name in meta["agent_npcs"]:
                    if name in self._npcs:
                        self.register_agent(name, (agent_llms or {}).get(name, llm))

    def close(self) -> None:
        """关闭各 NPC 记忆库和世界存储。"""
        for npc in self._npcs.values():
            try:
                npc.store.close()
            except Exception:
                pass
        if self._storage is not None:
            self._storage.close()
            self._storage = None
