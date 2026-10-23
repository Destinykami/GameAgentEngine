"""稻妻自治角色组装；模型与记忆目录由调用方提供。"""

from .definition import NPCS, REFLECT_THRESHOLD, TRAVELER_GOAL


def populate_world(w, llm, emb, data_dir: str) -> None:
    for name, traits, loc, hp, atk, dfn, role, goal in NPCS:
        w.add_npc(name, traits, llm=llm, embedder=emb, data_dir=data_dir,
                  location=loc, reflection_threshold=REFLECT_THRESHOLD,
                  autonomous=True)
        e = w.get(name)
        e.health, e.attack, e.defense, e.goal, e.role = hp, atk, dfn, goal, role
    w.add_agent_player("旅行者", "稻妻主城", TRAVELER_GOAL, llm=llm,
                       persona_traits={"social": 0.5, "goal_oriented": 0.9},
                       health=380, attack=12, defense=5)   # 血 300→380: 每 2h 一步后执行官持续追击的消耗翻倍,
                                     # 380 可撑完全程 (约 9 天满追击), 仍要应付搜捕
