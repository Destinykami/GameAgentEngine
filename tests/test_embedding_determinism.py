"""HashEmbedder 跨进程稳定性回归 (F0-1)。

内建 hash() 对字符串按进程随机加盐, 会让同一份文本在不同进程得到不同向量:
去重/检索在重启后漂移, 测试随 PYTHONHASHSEED 随机红。本测试用子进程分别以
不同种子重建 HashEmbedder, 断言向量逐元素一致。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys


from game_agent.models.embeddings import HashEmbedder, cosine_similarity

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_EMIT_VEC = (
    "import json;"
    "from game_agent.models.embeddings import HashEmbedder;"
    "print(json.dumps(HashEmbedder().embed(['Aria 帮 Klaus 修了咖啡机'])[0]))"
)


def _embed_in_subprocess(seed: int) -> list[float]:
    env = dict(os.environ, PYTHONHASHSEED=str(seed), PYTHONPATH=os.path.join(ROOT, "src"))
    out = subprocess.check_output(
        [sys.executable, "-c", _EMIT_VEC],
        cwd=ROOT, env=env, text=True, timeout=60)
    return json.loads(out.strip().splitlines()[-1])


def test_hash_embedder_stable_across_hash_seeds():
    """同一文本在 PYTHONHASHSEED=0/24 下必须得到相同向量。"""
    v0 = _embed_in_subprocess(0)
    v24 = _embed_in_subprocess(24)
    assert v0 == v24, "HashEmbedder 必须跨进程稳定 (不得使用内建 hash())"


def test_embedder_is_deterministic_in_process():
    emb = HashEmbedder()
    a = emb.embed(["雷电将军颁布眼狩令"])[0]
    b = emb.embed(["雷电将军颁布眼狩令"])[0]
    assert a == b


def test_unrelated_texts_are_not_identical():
    """稳定哈希仍可能有碰撞, 但语义/词面明显不同的两条文本不应近乎相同。"""
    emb = HashEmbedder()
    a, b = emb.embed(["Aria 帮 Klaus 修咖啡机", "雷电将军颁布眼狩令"])
    assert a != b
    assert cosine_similarity(a, b) < 0.92
