"""单次标准库 HTTP JSON 交互；不重试、不记账、不解释任务输出。"""

import json
import urllib.request
from typing import Any

from .config import EndpointConfig


def post_json(config: EndpointConfig, route: str, data: bytes) -> Any:
    req = urllib.request.Request(
        config.base_url + route, data=data, method="POST",
        headers={"Content-Type": "application/json",
                 **({"Authorization": f"Bearer {config.api_key}"}
                    if config.api_key else {})})
    with urllib.request.urlopen(req, timeout=config.timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))
