"""公共入口的按需导出；不加载具体引擎组件。"""

from importlib import import_module


def resolve_export(name, package, namespace, exports):
    try:
        module, attribute = exports[name]
    except KeyError:
        raise AttributeError(f"module {package!r} has no attribute {name!r}") from None
    value = getattr(import_module(module, package), attribute)
    namespace[name] = value
    return value
