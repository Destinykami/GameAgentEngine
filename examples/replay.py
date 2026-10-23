#!/usr/bin/env python3
"""终端/HTML 回放示例；原命令行参数及默认时间线路径保持不变。"""

import os

from game_agent.runners.replay.cli import main as run

DEFAULT_TL = os.path.join(os.path.dirname(__file__), "..", "data", "auto_sim", "timeline.json")


def main() -> int:
    return run(DEFAULT_TL)


if __name__ == "__main__":
    raise SystemExit(main())
