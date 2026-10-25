"""脚本周剧情的依赖组装、运行目录与世界生命周期。"""

import os

from ..models.llm_http import RealLLM
from ..models.embeddings_http import make_embedder
from ..world.runtime import World
from ..scenarios.inazuma.definition import (SCRIPTED_LOCATIONS as LOCATIONS,
                                            SCRIPTED_NPCS as NPCS,
                                            SCRIPTED_REFLECT_THRESHOLD as REFLECT_THRESHOLD)
from ..scenarios.inazuma.scripted import play_week
from .artifacts import reset_directory


def run(data_dir: str, *, llm_factory=RealLLM, embedder_factory=make_embedder) -> int:
    reset_directory(data_dir)
    llm = llm_factory()
    emb = embedder_factory()
    w = World("稻妻城", LOCATIONS, path=os.path.join(data_dir, "world.db"))
    try:
        for name, persona, loc, _ in NPCS:
            w.add_npc(name, persona, llm=llm, embedder=emb, data_dir=data_dir,
                      location=loc, reflection_threshold=REFLECT_THRESHOLD)
        w.add_player("旅行者", "稻妻主城")

        play_week(w)
        w.save_checkpoint(os.path.join(data_dir, "checkpoints"))
    finally:
        w.close()
    print(f"\n世界状态已存: {os.path.abspath(data_dir)}/world.db  (每 NPC 独立 <name>.db)")
    print("可用 tools/inspect_npc.py data/sim/<name>.db 深入审查任一 NPC 的记忆流与证据链。")
    return 0
