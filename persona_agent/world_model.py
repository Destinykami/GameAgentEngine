"""世界实体与空间模型；不依赖认知、运行器或持久化。"""

from __future__ import annotations

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


