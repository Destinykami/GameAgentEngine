"""集成探针 pytest: 对真实 LLM 断言千人千面不退化。

需网络可达 10.121.39.10:30005; 不可达时自动 skip (非硬失败)。
"""

from __future__ import annotations


import pytest


from game_agent.evaluation.probes import (
    _llm_available, build_scenario, probe_consistency,
    probe_non_omniscience, probe_persistence, probe_drift,
    probe_first_person, probe_world_isolation,
)


@pytest.fixture(scope="module")
def scenario():
    if not _llm_available():
        pytest.skip("LLM 端点不可达, 跳过集成探针")
    return build_scenario()


def test_consistency(scenario):
    npc, now = scenario
    r = probe_consistency(npc, now)
    assert r.passed, r.detail


def test_non_omniscience():
    if not _llm_available():
        pytest.skip("LLM 端点不可达, 跳过集成探针")
    from game_agent.evaluation.probes import _make_npc  # noqa: F401  (仅确保导入)
    r = probe_non_omniscience(40.0)
    assert r.passed, r.detail


def test_persistence(scenario):
    npc, now = scenario
    r = probe_persistence(npc, now)
    assert r.passed, r.detail


def test_drift(scenario):
    npc, now = scenario
    r = probe_drift(npc, now)
    assert r.passed, r.detail


def test_first_person(scenario):
    npc, now = scenario
    r = probe_first_person(npc, now)
    assert r.passed, r.detail


def test_world_isolation():
    if not _llm_available():
        pytest.skip("LLM 端点不可达, 跳过集成探针")
    r = probe_world_isolation(40.0)
    assert r.passed, r.detail
