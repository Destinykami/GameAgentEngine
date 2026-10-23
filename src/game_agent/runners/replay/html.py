"""静态 HTML 时间线输出；保留原模板与转义范围。"""

import html


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
                if cfg.get("reason_needed") is None:   # B+ 涌现: 无门控
                    extra = (f"<span class='meta'>证据{len(s['reasons'])}条 "
                             f"攻{s['attack']}</span>")
                else:
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
    if last["decree_ended"]:
        how = "阵亡" if last["shogun_dead"] else "被说服 (LLM 裁决)"
        ending = f"眼狩令已废止 (将军{how})。旅行者目标达成。"
    elif cfg.get("persuade_n") is None:
        ending = (f"眼狩令仍在 (旅程未让将军废止)。旅行者证据 "
                   f"{len(last['states']['旅行者']['reasons'])} 条。")
    else:
        ending = f"眼狩令仍在。将军被劝说 {last['persuade']}/{cfg['persuade_n']} 次。"
    if cfg.get("reason_needed") is None:   # B+ 涌现副标题
        subtitle = ("<div class='sub'>旅行者目标: 说服雷电将军废止眼狩令 (B+ 涌现: "
                    "证据由 LLM 从对话生成, 是否被说服由 LLM 当场裁决, 结局未知)</div>")
    else:
        subtitle = (f"<div class='sub'>旅行者目标: 打败并说服雷电将军结束眼狩令 "
                    f"(双关: 理由≥{cfg['reason_needed']} 且攻≥{cfg['attack_needed']}, "
                    f"再当面劝说 {cfg['persuade_n']} 次)</div>")
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
{subtitle}
{''.join(cards)}<div class='ending'>{ending}</div></body></html>"""
