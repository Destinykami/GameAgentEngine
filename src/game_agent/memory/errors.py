"""原文归档失败的轻量异常契约，不依赖数据库。"""


class ArchiveWriteError(RuntimeError):
    """原文未能可靠落库；不得作为可忽略的派生处理失败。"""
