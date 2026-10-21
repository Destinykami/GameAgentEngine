"""用真实 LLM (SGLang @ 10.121.39.10:30005, Qwen3.8-27B-Coder) 的千人千面 demo。

端到端千人千面 demo, 对话/反思/规划全部走真实模型:
- 对话: 关思考 (快, in-character), 可用 enable_thinking=True 打开
- 打分/反思/规划等结构化任务: 恒关思考 (思考 token 会挤爆 max_tokens)

运行: python examples/demo_real.py
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from persona_agent import NPC, RealLLM, make_embedder

TRAITS = {"social": 0.4, "goal_oriented": 0.8}   # 目标导向为主, 社交为辅


def main() -> int:
    llm = RealLLM()   # 默认接入 10.121.39.10:30005
    npc = NPC("Klaus", TRAITS, llm=llm, embedder=make_embedder())

    print("=" * 72)
    print("千人千面 NPC demo (真实 LLM: Qwen3.8-27B-Coder @ SGLang)")
    print("人格: 目标导向为主, 社交为辅")
    print("=" * 72)

    print("\n[日计划] 生成并逐层分解 (结构化 JSON, 关思考):")
    npc.generate_daily_plan(previous_day="睡了个好觉", date="2月13日", now=7.0)
    plans = sorted(npc.store.all_valid(types=["plan"]), key=lambda p: p.timestamp)
    for p in plans[:8]:
        print(f"   {p.content}")

    print("\n[观察] Aria 的友善历史 / Bram 的背叛历史 (打分走真实 LLM, 关思考):")
    npc.observe("Aria 送给了 Klaus 一份礼物, 帮助他渡过难关", 10.0, "Aria")
    npc.observe("Aria 保护了 Klaus 免受伤害", 20.0, "Aria")
    npc.observe("Aria 帮助 Klaus 完成了研究项目", 30.0, "Aria")
    npc.observe("Bram 欺骗了 Klaus, 对他撒谎", 15.0, "Bram")
    npc.observe("Bram 爽约, 没有赴 Klaus 的约", 25.0, "Bram")
    npc.observe("Bram 偷走了 Klaus 的物品", 35.0, "Bram")

    npc.reflect_relationship("Aria", 40.0)
    npc.reflect_relationship("Bram", 40.0)
    print(f"[关系反思] Aria 信任度 = {npc.trust_toward('Aria'):+.2f}, "
          f"Bram 信任度 = {npc.trust_toward('Bram'):+.2f}")

    print("\n" + "-" * 72)
    print("[对话] 同一句 '你对我印象如何?' 两个玩家听到的回答 (关思考, in-character):")
    print("-" * 72)
    q = "你对我印象如何? 我们相处得怎么样?"
    a = npc.speak("Aria", q, 40.0)
    b = npc.speak("Bram", q, 40.0)
    print(f"  Aria: {a}")
    print(f"  Bram: {b}")
    print(f"  → 两者不同: {a != b}")

    print("\n" + "-" * 72)
    print("[反应] 同样一句派对邀请 (效用函数, 信任度调制):")
    print("-" * 72)
    ev = "Klaus, 周末的派对一起来吧!"
    da = npc.react(ev, "Aria", 40.0)
    db = npc.react(ev, "Bram", 40.0)
    print(f"  对Aria: {da.action}  (效用 {da.utility:.2f})")
    print(f"  对Bram: {db.action}  (效用 {db.utility:.2f})")

    ok = a != b
    print(f"\n总结: 千人千面对话 {'成立' if ok else '未体现'} "
          f"(Aria 与 Bram 的回答不同)")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
