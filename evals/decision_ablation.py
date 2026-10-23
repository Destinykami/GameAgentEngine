"""decision_ablation 命令行入口；只有 main 调用才执行评测。"""

import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evals.experiments.decision_ablation import main


if __name__ == "__main__":
    raise SystemExit(main())
