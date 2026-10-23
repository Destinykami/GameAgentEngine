"""评测 JSON 读写与终端格式，不创建模型或选择运行目录。"""

import json

def save_json(path: str, obj) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2, default=str)


def load_json(path: str):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def print_table(headers: list[str], rows: list[list]) -> None:
    """朴素对齐表格 (标准库, 无依赖)。"""
    widths = [max(len(str(h)), *(len(str(r[i])) for r in rows)) if rows
              else len(str(h))
              for i, h in enumerate(headers)]
    line = "  ".join(str(h).ljust(widths[i]) for i, h in enumerate(headers))
    print(line)
    print("-" * len(line))
    for r in rows:
        print("  ".join(str(c).ljust(widths[i]) for i, c in enumerate(r)))


def pct(x: float) -> str:
    return f"{x * 100:.1f}%"
