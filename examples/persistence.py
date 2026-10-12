"""persistence: NPC 持久化创建 + 记忆流落盘演示。

每个进程 = 一次"游戏会话"。状态跨会话累积:
  会话1 (create):  Isabella 不存在则新建; Aria 帮她整理菜单; 对话; 保存
  会话2 (load):    从 data/Isabella.db 加载; 验证会话1的记忆/信任还在;
                   新对话里她记得上一会话的事; 再保存

同一进程里先 create 再 load 走一遍完整往返; 也可以反复运行本脚本,
每跑一次就多一次会话的记忆 (data/Isabella.db 持续累积)。

跑法: python examples/persistence.py   (需 LLM 可达)
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from persona_agent import NPC, RealLLM, make_embedder

TRAITS = {"social": 0.8, "goal_oriented": 0.3}
DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")


def banner(title: str) -> None:
    print("\n" + "═" * 72)
    print(title)
    print("═" * 72)


def run_session(npc: NPC, session_no: int) -> None:
    now = 7.0 + (session_no - 1) * 24.0   # 每会话隔一天
    banner(f"游戏会话 {session_no}  (NPC: {npc.name}, 库: {npc.store.db_path()})")
    print(f"   加载时记忆总数: {npc.memory_count()}, "
          f"对Aria信任度: {npc.trust_toward('Aria'):+.2f}")

    # 本会话新事件
    npc.observe("Aria 又来咖啡馆, 帮 Isabella 整理菜单并试了新豆子",
                now + 2.0, player_id="Aria")
    print(f"   +1 观察 → 记忆总数: {npc.memory_count()}, "
          f"对Aria信任度: {npc.trust_toward('Aria'):+.2f}")

    # 对话: 加载的 NPC 应能回忆起之前会话的事
    reply = npc.speak("Aria", "你最近都在忙什么? 我们还聊过什么?", now + 3.0)
    print(f"   Aria: '你最近都在忙什么? 我们还聊过什么?'")
    print(f"   {npc.name}: {reply}")
    npc.save()
    print(f"   已保存 (游戏时钟: {npc._game_time:.1f}h)")


def main() -> int:
    banner("会话 1 — NPC.create (不存在则新建并落库)")
    isabella = NPC.create("Isabella", dict(TRAITS), llm=RealLLM(),
                          embedder=make_embedder(), data_dir=DATA_DIR)
    run_session(isabella, 1)
    isabella.store.close()

    banner("会话 2 — NPC.load (从磁盘恢复, 验证跨会话持久)")
    isabella2 = NPC.load(os.path.join(DATA_DIR, "Isabella.db"), llm=RealLLM(),
                         embedder=make_embedder())
    run_session(isabella2, 2)
    isabella2.store.close()

    print("\n完成: data/Isabella.db 已包含两次会话的全部记忆与元数据。")
    print("再跑一次本脚本, 会话3会在现有记忆之上继续累积。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
