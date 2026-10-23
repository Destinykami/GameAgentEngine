"""RealEmbedder: 接入真实 embedding 模型 (OpenAI 兼容 /v1/embeddings, 纯标准库)。

默认指向 gte-Qwen2-1.5B-instruct @ 10.121.39.10:30006。
与 HashEmbedder 的区别: 语义相似度 —— 换说法的同义句也能高相似,
这是反思去重/语义召回真正需要的能力。

make_embedder(): 优先真实端点, 不可达时自动回退 HashEmbedder (打警告),
让示例/探针在网络受限时也能跑。
"""

from __future__ import annotations

import json
import time
import urllib.error
from typing import Sequence

from .embeddings import Embedder
from .config import (DEFAULT_EMBEDDING_BASE_URL as DEFAULT_BASE_URL,
                     DEFAULT_EMBEDDING_MODEL as DEFAULT_MODEL, EndpointConfig)
from .transport import post_json

class RealEmbedder(Embedder):
    """调用远程 embedding 端点。embed(texts) 一次请求批量编码, 返回归一化向量。"""

    def __init__(self, base_url: str = DEFAULT_BASE_URL,
                 model: str = DEFAULT_MODEL, api_key: str | None = None,
                 timeout: float = 30.0, max_retries: int = 2) -> None:
        self.endpoint = EndpointConfig(base_url.rstrip("/"), model, api_key,
                                       timeout, max_retries)
        self._dim: int | None = None   # 首次 embed 后懒发现

    @property
    def dim(self) -> int:
        if self._dim is None:
            self.embed(["探测维度"])      # 懒发现
        assert self._dim is not None
        return self._dim

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        texts = list(texts)
        payload = json.dumps({"model": self.endpoint.model, "input": texts}).encode("utf-8")
        last_err: Exception | None = None
        for attempt in range(self.endpoint.max_retries + 1):
            try:
                payload_out = post_json(self.endpoint, "/v1/embeddings", payload)
                items = payload_out["data"]
                items.sort(key=lambda d: d.get("index", 0))
                vecs = [self._normalize(d["embedding"]) for d in items]
                if self._dim is None and vecs:
                    self._dim = len(vecs[0])
                return vecs
            except (urllib.error.URLError, urllib.error.HTTPError,
                    TimeoutError, OSError, KeyError, json.JSONDecodeError,
                    IndexError, ValueError) as e:
                last_err = e
                if attempt < self.endpoint.max_retries:
                    time.sleep(1.0 * (attempt + 1))
                    continue
                raise RuntimeError(f"embedding 请求失败: {e}") from e
        raise RuntimeError(f"embedding 请求失败: {last_err}")

    @staticmethod
    def _normalize(vec: Sequence[float]) -> list[float]:
        norm = sum(x * x for x in vec) ** 0.5
        if norm == 0.0:
            return list(vec)
        return [x / norm for x in vec]


def make_embedder(prefer_real: bool = True,
                  verbose: bool = True) -> Embedder:
    """优先真实语义 embedding; 端点不可达时回退 HashEmbedder。"""
    from .embeddings import HashEmbedder
    if not prefer_real:
        return HashEmbedder()
    try:
        emb = RealEmbedder()
        emb.embed(["连通性探测"])
        return emb
    except Exception as e:
        if verbose:
            print(f"[embedder] 真实端点不可达 ({e}), 回退 HashEmbedder (词袋)")
        return HashEmbedder()
