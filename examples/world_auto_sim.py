#!/usr/bin/env python3
"""稻妻自治示例；规则、组装与运行产物分别由正式模块管理。"""

import os

from game_agent.runners.artifacts import RunPaths
from game_agent.runners.inazuma import run

DATA = os.path.join(os.path.dirname(__file__), "..", "data", "auto_sim")
LIVE_JSONL = os.path.join(os.path.dirname(__file__), "..", "visualization", "public", "live.jsonl")


def main() -> int:
    return run(RunPaths(DATA, LIVE_JSONL))


if __name__ == "__main__":
    raise SystemExit(main())
