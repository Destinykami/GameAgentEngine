"""终端回放文本及原暂停节奏。"""

import time


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
            if cfg.get("reason_needed") is None:   # B+ 涌现: 无门控, 只显示证据数/攻
                extra = f"  证据{len(s['reasons'])}条 攻{s['attack']}"
            else:
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
        how = "阵亡" if last["shogun_dead"] else "被说服 (LLM 裁决)"
        print(f"\n   ★ 眼狩令已废止 (将军{how})。旅行者目标达成。")
    elif cfg.get("persuade_n") is None:
        print(f"\n   眼狩令仍在 (旅程未让将军废止)。旅行者证据 "
              f"{len(last['states']['旅行者']['reasons'])} 条。")
    else:
        print(f"\n   眼狩令仍在。将军被劝说 {last['persuade']}/{cfg['persuade_n']} 次。")
