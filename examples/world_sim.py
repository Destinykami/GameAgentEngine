"""稻妻脚本周剧情示例；仅指定运行路径并调用正式运行器。"""

import os

from game_agent.runners.scripted import run

DATA = os.path.join(os.path.dirname(__file__), "..", "data", "sim")


def main() -> int:
    return run(DATA)


if __name__ == "__main__":
    raise SystemExit(main())
