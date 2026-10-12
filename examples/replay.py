#!/usr/bin/env python3
"""replay.py — 回放 world_auto_sim 记录的时间线 (让世界在终端/网页里重演)。

读 data/auto_sim/timeline.json (由 world_auto_sim.py 生成), 逐步回放:
每步显示 时间 / 各 agent 的动作与对话 / 状态 (血条+位置+旅行者理由与攻) /
劝说进度与结局。终端回放按 --delay 节奏演; --html 另生成网页时间线。

用法:
  .venv/bin/python examples/replay.py                 # 终端回放, 每步停 1.5s
  .venv/bin/python examples/replay.py --delay 3       # 放慢
  .venv/bin/python examples/replay.py --no-delay      # 一次打完 (不暂停)
  .venv/bin/python examples/replay.py --html          # 额外生成 data/auto_sim/replay.html
  .venv/bin/python examples/replay.py --file 路径.json
"""
from __future__ import annotations

import argparse
import html
import json
import os
import sys
import time

HERE = os.path.dirname(__file__)
DEFAULT_TL = os.path.join(HERE, "..", "data", "auto_sim", "timeline.json")


def load(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def bar(hp: int, max_hp: int, width: int = 10) -> str:
    """血条: [████░░░░░░]。"""
    frac = max(0.0, min(1.0, hp / max_hp)) if max_hp else 0.0
    filled = int(round(frac * width))
    return "[" + "█" * filled + "░" * (width - filled) + "]"


def render_step(step: dict, cfg: dict) -> str:
    """把一个步骤渲染成终端文本块。"""
    day, moment = step["day"], step["moment"]
    lines = [f"═══ 第 {day} 天 {int(moment):02d}:00 " + "═" * 40]
    for ev in step["events"]:
        lines.append("   " + ev)
    if step.get("note"):
        lines.append("   ★ " + step["note"])
    # 状态: 血条 + 位置; 旅行者加理由/攻
    lines.append("   ── 状态 ──")
    states = step["states"]
    max_hp = {n: max(1, s["health"]) for n, s in states.items()}
    # 用初始 (第0步) 的血当满值更合理, 但这里近似用当前最大值
    for name, s in states.items():
        if s["dead"]:
            lines.append(f"   {name:<6} ✝ 阵亡")
            continue
        b = bar(s["health"], max_hp[name])
        extra = ""
        if s["kind"] == "player":
            extra = (f"  理由{len(s['reasons'])}/{cfg['reason_needed']} "
                     f"攻{s['attack']}/{cfg['attack_needed']}")
        lines.append(f"   {name:<6} {b} {s['health']:>3} @{s['loc']}{extra}")
    lines.append("")
    return "\n".join(lines)


def play_terminal(tl: dict, delay: float, no_delay: bool) -> None:
    cfg = tl
    steps = tl["steps"]
    for i, step in enumerate(steps):
        print(render_step(step, cfg), flush=True)
        if not no_delay and delay > 0 and i < len(steps) - 1:
            time.sleep(delay)
    # 结局
    last = steps[-1]
    print("═══ 结局 " + "═" * 50)
    states = last["states"]
    for name, s in states.items():
        tag = "✝" if s["dead"] else f"血{s['health']}@{s['loc']}"
        print(f"   {name:<6} {tag}")
    if last["decree_ended"]:
        how = "阵亡" if last["shogun_dead"] else f"被劝说 {last['persuade']} 次"
        print(f"\n   ★ 眼狩令已废止 (将军{how})。旅行者目标达成。")
    else:
        print(f"\n   眼狩令仍在。将军被劝说 {last['persuade']}/{cfg['persuade_n']} 次。")


def render_html(tl: dict) -> str:
    """生成自包含 HTML 时间线网页。"""
    cfg = tl
    steps = tl["steps"]
    cards = []
    for step in steps:
        evs = "".join(f"<div class='ev'>{html.escape(e)}</div>" for e in step["events"])
        note = (f"<div class='note'>★ {html.escape(step['note'])}</div>"
                if step.get("note") else "")
        rows = []
        states = step["states"]
        max_hp = {n: max(1, s["health"]) for n, s in states.items()}
        for name, s in states.items():
            if s["dead"]:
                rows.append(f"<div class='row dead'><span class='nm'>{name}</span>"
                            f"<span class='hpbar'><i style='width:0%'></i></span>"
                            f"<span class='hp'>✝</span></div>")
                continue
            pct = int(round(100 * s["health"] / max_hp[name]))
            extra = ""
            if s["kind"] == "player":
                extra = (f"<span class='meta'>理由{len(s['reasons'])}/{cfg['reason_needed']}"
                         f" 攻{s['attack']}/{cfg['attack_needed']}</span>")
            rows.append(f"<div class='row'><span class='nm'>{name}</span>"
                        f"<span class='hpbar'><i style='width:{pct}%'></i></span>"
                        f"<span class='hp'>{s['health']} @{s['loc']}</span>{extra}</div>")
        cls = "card end" if step["decree_ended"] else "card"
        cards.append(f"<section class='{cls}'><h2>第 {step['day']} 天 "
                     f"{int(step['moment']):02d}:00</h2>{evs}{note}"
                     f"<div class='rows'>{''.join(rows)}</div></section>")
    last = steps[-1]
    ending = ("眼狩令已废止 (将军" + ("阵亡" if last["shogun_dead"]
             else f"被劝说 {last['persuade']} 次") + ")。旅行者目标达成。"
              if last["decree_ended"] else
              f"眼狩令仍在。将军被劝说 {last['persuade']}/{cfg['persuade_n']} 次。")
    return f"""<!doctype html><html lang='zh'><head><meta charset='utf-8'>
<title>稻妻城 · 多智能体自治回放</title><style>
body{{font-family:system-ui,'PingFang SC',sans-serif;background:#1a1a1f;color:#e8e6e3;
margin:0;padding:24px}} h1{{font-weight:600}} .card{{background:#232329;border:1px solid
#333;border-radius:10px;padding:14px 18px;margin:12px 0}} .card.end{{border-color:#b08d57}}
h2{{margin:0 0 8px;font-size:15px;color:#b08d57}} .ev{{font-size:14px;line-height:1.5;
padding:2px 0}} .note{{color:#e0b34d;font-weight:600;margin:6px 0}} .rows{{margin-top:8px;
border-top:1px solid #333;padding-top:8px}} .row{{display:flex;align-items:center;gap:10px;
padding:2px 0;font-size:13px}} .row.dead{{opacity:.5}} .nm{{width:56px}} .hpbar{{flex:0 0
140px;height:10px;background:#3a3a42;border-radius:5px;overflow:hidden}} .hpbar i{{display:
block;height:100%;background:linear-gradient(90deg,#c0563a,#d99a3c)}} .hp{{width:120px;
color:#9a9aa2}} .meta{{color:#7fb0c9;font-size:12px}} .ending{{background:#2a2419;border:1px
solid #b08d57;border-radius:10px;padding:14px 18px;margin-top:16px;color:#e0b34d;font-weight:600}}
</style></head><body><h1>稻妻城 · 多智能体自治回放</h1>
<div class='sub'>旅行者目标: 打败并说服雷电将军结束眼狩令 (双关: 理由≥{cfg['reason_needed']}
且攻≥{cfg['attack_needed']}, 再当面劝说 {cfg['persuade_n']} 次)</div>
{''.join(cards)}<div class='ending'>{ending}</div></body></html>"""


def main() -> int:
    ap = argparse.ArgumentParser(description="回放 world_auto_sim 时间线")
    ap.add_argument("--file", default=DEFAULT_TL, help="timeline.json 路径")
    ap.add_argument("--delay", type=float, default=1.5, help="每步暂停秒数 (默认1.5)")
    ap.add_argument("--no-delay", action="store_true", help="不暂停, 一次打完")
    ap.add_argument("--html", action="store_true", help="额外生成 replay.html")
    args = ap.parse_args()
    tl = load(args.file)
    play_terminal(tl, args.delay, args.no_delay)
    if args.html:
        out = os.path.join(os.path.dirname(args.file), "replay.html")
        with open(out, "w", encoding="utf-8") as f:
            f.write(render_html(tl))
        print(f"\n网页时间线已生成: {os.path.abspath(out)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
