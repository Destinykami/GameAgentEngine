"""聊天传输重试与统计时机，不解释提示词或任务结果。"""

from __future__ import annotations

import json
import time
import urllib.error
from collections.abc import Callable
from typing import Any

from ..config import EndpointConfig
from ..transport import post_json


def request_chat(config: EndpointConfig, record: Callable[[str, float, dict], None],
                 system: str, user: str, *, think: bool = False,
                 temperature: float = 0.0, max_tokens: int = 512,
                 _stats_tag: str = "unspecified") -> str:
    body: dict[str, Any] = {
        "model": config.model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
        # 思考型模型: 按调用决定是否思考
        "chat_template_kwargs": {"enable_thinking": think},
    }
    data = json.dumps(body).encode("utf-8")
    last_err: Exception | None = None
    for attempt in range(config.max_retries + 1):
        t0 = time.monotonic()
        try:
            payload = post_json(config, "/v1/chat/completions", data)
            record(_stats_tag, time.monotonic() - t0,
                   payload.get("usage") or {})
            msg = payload["choices"][0]["message"]
            return msg.get("content") or ""
        except (urllib.error.URLError, urllib.error.HTTPError,
                TimeoutError, OSError, KeyError, json.JSONDecodeError) as e:
            record(_stats_tag, time.monotonic() - t0, {})
            last_err = e
            if attempt < config.max_retries:
                time.sleep(1.0 * (attempt + 1))
                continue
            raise RuntimeError(f"LLM 请求失败: {e}") from e
    raise RuntimeError(f"LLM 请求失败: {last_err}")
