"""兼容导入；实现位于 game_agent.models.llm_http。"""

from importlib import import_module as _import_module
import sys as _sys

_sys.modules[__name__] = _import_module("game_agent.models.llm_http")
