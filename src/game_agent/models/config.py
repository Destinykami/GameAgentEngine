"""每实例模型连接参数及原部署默认值，不读取环境或连接端点。"""

from dataclasses import dataclass, field

DEFAULT_LLM_BASE_URL = "http://10.121.39.10:30005"
DEFAULT_LLM_MODEL = "/data/models/Qwen3.8-27B-Coder/BF16"
DEFAULT_EMBEDDING_BASE_URL = "http://10.121.39.10:30006"
DEFAULT_EMBEDDING_MODEL = "Alibaba-NLP/gte-Qwen2-1.5B-instruct"


@dataclass(frozen=True)
class EndpointConfig:
    base_url: str
    model: str
    api_key: str | None = field(default="", repr=False)
    timeout: float = 60.0
    max_retries: int = 2
