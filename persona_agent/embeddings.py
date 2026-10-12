"""向量层: 可插拔 Embedder 接口。

默认 HashEmbedder: 基于词袋 + 哈希的确定性向量, 无需模型权重即可跑通,
余弦相似度反映词面重叠, 足够支撑 demo 与探针测试的"相关性"维度。
接入真实模型时, 实现 embed(texts) -> list[list[float]] 并保证归一化即可。
"""

from __future__ import annotations

import math
import re
from abc import ABC, abstractmethod
from typing import Iterable, Sequence

# 英文/数字按连续串成词, 中文按单字 —— 否则 "咖啡馆的运营" 和 "咖啡馆运营"
# 会被当成两个零重叠的整串 token, 词面信号严重漏检。
_TOKEN_RE = re.compile(r"[a-z0-9]+|[\u4e00-\u9fff]")


def _tokens(text: str) -> list[str]:
    """简单分词: 英文按词, 中文按单字, 保证中英文都能产生重叠信号。"""
    return _TOKEN_RE.findall(text.lower())


class Embedder(ABC):
    """Embedder 接口: 把文本变成归一化向量。"""

    @property
    @abstractmethod
    def dim(self) -> int:
        """向量维度。"""

    @abstractmethod
    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """批量编码, 返回与输入等长的归一化向量。"""


def cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    """余弦相似度。输入应为归一化向量, 但仍做安全处理。"""
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


class HashEmbedder(Embedder):
    """词袋哈希 Embedder: 确定性、无外部依赖、中英文均可用。"""

    def __init__(self, dim: int = 256) -> None:
        self._dim = dim

    @property
    def dim(self) -> int:
        return self._dim

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._embed_one(t) for t in texts]

    def _embed_one(self, text: str) -> list[float]:
        vec = [0.0] * self._dim
        for tok in _tokens(text):
            # 用稳定哈希决定桶与符号, 降低碰撞抵消
            h = hash(tok) & 0xFFFFFFFF
            idx = h % self._dim
            sign = 1.0 if (h >> 16) & 1 else -1.0
            vec[idx] += sign
        norm = math.sqrt(sum(x * x for x in vec))
        if norm > 0:
            vec = [x / norm for x in vec]
        return vec

    def embed_batch_or_empty(self, texts: Iterable[str]) -> list[list[float]]:
        return self.embed(list(texts))
