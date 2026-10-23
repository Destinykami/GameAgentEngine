"""规划模块公共入口，按需加载生成引擎与计划状态。"""

from ..._lazy import resolve_export as _resolve_export

_EXPORTS = {
    "PlanningEngine": (".engine", "PlanningEngine"),
    "PlanState": (".state", "PlanState"),
}

__all__ = list(_EXPORTS)


def __getattr__(name: str):
    return _resolve_export(name, __name__, globals(), _EXPORTS)


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
