"""模型适配器的离线 HTTP、重试、统计、JSON 修复与向量契约。"""

import json

import pytest

from game_agent.models import HashEmbedder, LLMContext, RealEmbedder, RealLLM
from game_agent.models import embeddings_http, transport
from game_agent.models.llm_http import parsing
from game_agent.models.llm_http import transport as chat_transport


def fake_http(monkeypatch, responses):
    responses = iter(responses)
    calls = []

    class Response:
        def __init__(self, raw):
            self.raw = raw

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def read(self):
            return self.raw

    def request(request, timeout):
        calls.append((request.full_url, json.loads(request.data), request.headers, timeout))
        response = next(responses)
        if isinstance(response, Exception):
            raise response
        return Response(response if isinstance(response, bytes) else json.dumps(response).encode())

    monkeypatch.setattr(transport.urllib.request, "urlopen", request)
    return calls


def payload(content="回答", usage=None):
    return {"choices": [{"message": {"content": content}}], "usage": usage or {}}


def test_chat_request_body_auth_retry_and_usage_are_per_attempt(monkeypatch):
    calls = fake_http(monkeypatch, [OSError("down"), payload("回答", {"prompt_tokens": 7,
                                                                      "completion_tokens": 3})])
    sleeps = []
    monkeypatch.setattr(chat_transport.time, "sleep", sleeps.append)
    ticks = iter([1, 2, 3, 5])
    monkeypatch.setattr(chat_transport.time, "monotonic", lambda: next(ticks))
    llm = RealLLM("http://offline///", "test-model", "secret", timeout=2, max_retries=2)
    assert llm.ask("问题", think=True, temperature=0.4, max_tokens=12) == "回答"
    assert len(calls) == 2 and calls[0] == calls[1] and sleeps == [1]
    url, body, headers, timeout = calls[0]
    assert url == "http://offline/v1/chat/completions" and timeout == 2
    assert headers["Authorization"] == "Bearer secret"
    assert body == {"model": "test-model", "messages": [
        {"role": "system", "content": "你是一个简洁的助手。"},
        {"role": "user", "content": "问题"}], "temperature": 0.4, "max_tokens": 12,
        "chat_template_kwargs": {"enable_thinking": True}}
    assert llm.stats["calls"] == 2 and llm.stats["total_latency_s"] == 3
    assert llm.stats["prompt_tokens"] == 7 and llm.stats["completion_tokens"] == 3
    assert llm.stats["by_method"]["ask"]["calls"] == 2
    previous = llm.stats
    llm.reset_stats()
    assert previous["calls"] == 2 and llm.stats["calls"] == 0
    assert RealLLM().stats["by_method"] == {}
    assert "secret" not in repr(llm.endpoint)


def test_chat_bad_choices_retains_original_usage_then_failure_accounting(monkeypatch):
    fake_http(monkeypatch, [{"usage": {"prompt_tokens": 9}}])
    llm = RealLLM(max_retries=0)
    with pytest.raises(RuntimeError, match="LLM 请求失败"):
        llm.ask("问题")
    assert llm.stats["calls"] == 2 and llm.stats["prompt_tokens"] == 9


@pytest.mark.parametrize("response,exception", [
    (b"bad-json", RuntimeError), (TimeoutError("timeout"), RuntimeError),
    ({"choices": []}, IndexError), ({"choices": None}, TypeError),
])
def test_chat_failure_catch_scope_and_final_error(monkeypatch, response, exception):
    fake_http(monkeypatch, [response])
    llm = RealLLM(max_retries=0)
    with pytest.raises(exception):
        llm.ask("问题")
    assert llm.stats["calls"] == 1


def test_json_repair_once_uses_original_suffix_and_zero_temperature():
    calls = []
    outputs = iter(["bad", '```json\n["已修复"]\n```'])

    def request(system, user, **options):
        calls.append((system, user, options))
        return next(outputs)

    assert parsing.request_json(request, "system", "user", temperature=0.7,
                                _stats_tag="plan") == ["已修复"]
    assert calls[1][1] == "user\n\n只输出 JSON, 不要任何其他文字。"
    assert calls[0][2]["temperature"] == 0.7 and calls[1][2]["temperature"] == 0
    assert all(c[2]["_stats_tag"] == "plan" for c in calls)
    with pytest.raises(json.JSONDecodeError):
        parsing.request_json(lambda *args, **kw: "bad", "system", "user")


def test_complete_empty_memories_skips_requests_and_thinking_only_applies_to_dialogue(monkeypatch):
    llm = RealLLM(enable_thinking=True)
    calls = []
    monkeypatch.setattr(llm, "_chat", lambda *args, **kw: calls.append(kw) or "5")
    assert llm.complete(LLMContext()) == "我对此没有印象。" and calls == []
    llm.complete(LLMContext(memories=[{"type": "observation", "content": "记忆"}]))
    llm.score_importance("记忆")
    assert [call["think"] for call in calls] == [True, False]


def test_embedding_batch_sort_normalize_dim_and_empty_request(monkeypatch):
    calls = fake_http(monkeypatch, [{"data": [
        {"index": 1, "embedding": [0, 0]}, {"index": 0, "embedding": [3, 4]}]},
        {"data": []}])
    embedder = RealEmbedder("http://offline/", "vector-model", timeout=4)
    assert embedder.embed(iter(["甲", "乙"])) == [[0.6, 0.8], [0, 0]]
    assert embedder.dim == 2 and len(calls) == 1
    assert embedder.embed([]) == [] and len(calls) == 2
    assert calls[0][0] == "http://offline/v1/embeddings" and calls[0][3] == 4
    assert calls[0][1] == {"model": "vector-model", "input": ["甲", "乙"]}
    assert calls[1][1]["input"] == [] and "Authorization" not in calls[0][2]


def test_embedding_lazy_dim_failure_retry_and_fallback(monkeypatch, capsys):
    calls = fake_http(monkeypatch, [ValueError("bad"), {"data": [{"embedding": [1, 0, 0]}]}])
    sleeps = []
    monkeypatch.setattr(embeddings_http.time, "sleep", sleeps.append)
    embedder = RealEmbedder(max_retries=1)
    assert embedder.dim == 3 and len(calls) == 2 and sleeps == [1]
    assert calls[0][1]["input"] == ["探测维度"]

    def fail(self, texts):
        raise RuntimeError("offline")

    monkeypatch.setattr(RealEmbedder, "embed", fail)
    assert isinstance(embeddings_http.make_embedder(verbose=False), HashEmbedder)
    assert capsys.readouterr().out == ""
    assert isinstance(embeddings_http.make_embedder(prefer_real=False), HashEmbedder)
    assert isinstance(embeddings_http.make_embedder(), HashEmbedder)
    assert "回退 HashEmbedder" in capsys.readouterr().out
