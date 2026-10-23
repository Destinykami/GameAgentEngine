"""仓库评测的原默认目录与时间戳策略。"""

import os
import time

DATA_ROOT = os.path.join(os.path.dirname(__file__), "..", "data", "eval")


def run_dir(exp_name: str) -> str:
    """每次跑批的产物目录: data/eval/<exp>/<时间戳>/ (被 .gitignore 挡住)。"""
    d = os.path.join(DATA_ROOT, exp_name, time.strftime("%Y%m%d-%H%M%S"))
    os.makedirs(d, exist_ok=True)
    return d
