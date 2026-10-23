"""只读 JSON 加载与回放命令行分发，默认路径由示例入口提供。"""

import argparse
import json
import os

from .terminal import play_terminal
from .html import render_html


def load(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def main(default_timeline: str) -> int:
    ap = argparse.ArgumentParser(description="回放 world_auto_sim 时间线")
    ap.add_argument("--file", default=default_timeline, help="timeline.json 路径")
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
