"""game_loop: 一个完整的游戏分钟 —— 从引擎视角演示 persona_agent 的用法。

场景: 咖啡馆店员 Isabella (外向 social 0.8 / 低目标导向 0.3)。
时间线 (游戏内小时):
  ① 07:00  开始一天                → generate_daily_plan (层次化规划)
  ② 09:00  玩家 Aria 进店帮忙      → observe (关系事件, 带 player_id)
  ③ 09:15  Aria: "你最近忙什么?"   → speak (自动反思门控 + 非全知对话)
  ④ 09:30  Aria 邀请她参加派对     → react (效用决策) → replan
  ⑤ 09:45  环境事件: 早餐着火了    → observe (世界事件) + react → replan
  ⑥ 10:00  Aria: "你还好吗?"      → speak (记忆已包含着火事件)
  ⑦ 对比: 骗过她的 Bram 同样邀请   → observe (背叛事件) + react → 拒绝

引擎侧只需做一件事: 把游戏事件翻译成一句自然语言喂给 observe()。
跑法: python examples/game_loop.py   (需 LLM 可达, 全程真实模型)
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from persona_agent import NPC, RealLLM, make_embedder


def banner(title: str) -> None:
    print("\n" + "─" * 72)
    print(title)
    print("─" * 72)


def main() -> int:
    isabella = NPC(
        "Isabella",
        {"social": 0.8, "goal_oriented": 0.3},   # 外向爱交友, 低目标导向
        llm=RealLLM(),
        embedder=make_embedder(),
    )

    banner("① 07:00 开始一天 — generate_daily_plan (人格驱动计划)")
    isabella.generate_daily_plan(
        previous_day="整理了情人节派对的装饰", date="2月13日", now=7.0)
    for p in sorted(isabella.store.all_valid(types=["plan"]),
                    key=lambda x: x.timestamp)[:6]:
        print(f"   {p.content}")

    banner("② 09:00 玩家Aria进店, 帮她补咖啡豆 — observe (关系事件)")
    isabella.observe("Aria 帮 Isabella 补了咖啡豆, 还聊了两句", 9.0, player_id="Aria")
    print(f"   对Aria信任度: {isabella.trust_toward('Aria'):+.2f}")

    banner("③ 09:15 Aria: '你最近忙什么?' — speak (反思门控 + 非全知)")
    print(f"   {isabella.speak('Aria', '你最近忙什么?', 9.25)}")

    banner("④ 09:30 Aria 邀请她参加今晚的派对 — react → replan")
    d = isabella.react("Aria 邀请 Isabella 去参加今晚的派对", "Aria", 9.5)
    print(f"   {d.action}  (效用 {d.utility:.2f})")
    print(f"   理由: {d.reason}")
    if d.react:
        isabella.replan(9.5, "接受Aria的派对邀请")
        print("   → 已从当前时刻重规划后续计划")

    banner("⑤ 09:45 环境事件: 早餐着火了 — observe (世界事件) + react")
    isabella.observe("早餐着火了, Isabella 看到了烟雾", 9.75)   # 世界事件不带 player_id
    d = isabella.react("早餐着火了, 需要关炉子", player_id=None, now=9.75)
    print(f"   {d.action}  (效用 {d.utility:.2f})")
    if d.react:
        isabella.replan(9.75, "处理火灾")
        print("   → 已从当前时刻重规划 (火灾打断原计划)")

    banner("⑥ 10:00 Aria: '你还好吗?' — speak (记忆已含着火)")
    print(f"   {isabella.speak('Aria', '你还好吗? 刚才那阵烟怎么回事?', 10.0)}")

    banner("⑦ 对比: 骗过她的 Bram 发出同样的派对邀请")
    isabella.observe("Bram 骗 Isabella 说他付了咖啡钱, 其实一直没付", 10.1, player_id="Bram")
    print(f"   对Bram信任度: {isabella.trust_toward('Bram'):+.2f}")
    d = isabella.react("Bram 邀请 Isabella 去参加今晚的派对", "Bram", 10.1)
    print(f"   {d.action}  (效用 {d.utility:.2f})")
    print(f"   理由: {d.reason}")

    banner("结局: 同一句邀请, 两个玩家, 两种待遇 — 这就是千人千面")
    print(f"   Aria 信任度 {isabella.trust_toward('Aria'):+.2f} → "
          f"{'接受' if isabella.trust_toward('Aria') > 0 else '拒绝'}")
    print(f"   Bram 信任度 {isabella.trust_toward('Bram'):+.2f} → "
          f"{'接受' if isabella.trust_toward('Bram') > 0 else '拒绝'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
