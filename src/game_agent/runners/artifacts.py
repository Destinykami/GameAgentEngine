"""运行目录与时间线 JSON/JSONL；不包含模型或场景规则。"""

from dataclasses import dataclass
import json
import os
import shutil


@dataclass(frozen=True)
class RunPaths:
    data_dir: str
    live_path: str

    @property
    def timeline_path(self) -> str:
        return os.path.join(self.data_dir, "timeline.json")


def reset_directory(path: str) -> None:
    """仅显式启动新运行时覆盖该运行目录，保留原入口行为。"""
    shutil.rmtree(path, ignore_errors=True)
    os.makedirs(path, exist_ok=True)


class TimelineWriter:
    def __init__(self, live_path: str, metadata: dict) -> None:
        self.steps: list[dict] = []
        self._live = open(live_path, "w", encoding="utf-8")
        self._write({"__meta__": True, **metadata})

    def _write(self, record: dict) -> None:
        self._live.write(json.dumps(record, ensure_ascii=False) + "\n")
        self._live.flush()

    def append(self, step: dict) -> None:
        self.steps.append(step)
        self._write(step)

    def finish(self, flags: dict) -> None:
        self._write({"__done__": True, **flags})
        self._live.close()

    def write_final(self, path: str, metadata: dict) -> None:
        with open(path, "w", encoding="utf-8") as stream:
            json.dump({**metadata, "steps": self.steps}, stream,
                      ensure_ascii=False, indent=2)
