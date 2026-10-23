"""models 模块公共入口；实现按需加载。"""

from .._lazy import resolve_export as _resolve_export

_EXPORTS = {
    'LLMClient': ('.llm', 'LLMClient'),
    'LLMContext': ('.llm', 'LLMContext'),
    'RealLLM': ('.llm_http', 'RealLLM'),
    'Embedder': ('.embeddings', 'Embedder'),
    'HashEmbedder': ('.embeddings', 'HashEmbedder'),
    'RealEmbedder': ('.embeddings_http', 'RealEmbedder'),
    'make_embedder': ('.embeddings_http', 'make_embedder'),
}

__all__ = list(_EXPORTS)


def __getattr__(name: str):
    return _resolve_export(name, __name__, globals(), _EXPORTS)


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
