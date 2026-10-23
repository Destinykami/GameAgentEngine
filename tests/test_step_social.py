"""step 消费社交队列回归 (F3-2)。

`social_perception` 在 perceive 里登记 _step_social; step 必须在步末 flush,
否则队列跨步积压、关系反思永不跑 (此前只有 step_autonomous 会 flush)。
"""

from __future__ import annotations



from game_agent import Location, World
from tests.test_persistence import _StubLLM, TRAITS


def _world(tmp_path) -> World:
    w = World("w", [Location("L", 0, 0)], social_perception=True)
    w.add_npc("A", dict(TRAITS), llm=_StubLLM(),
              data_dir=str(tmp_path / "A"), location="L")
    w.add_npc("B", dict(TRAITS), llm=_StubLLM(),
              data_dir=str(tmp_path / "B"), location="L")
    w.add_player("P", "L")
    return w


def test_step_flushes_social_queue_and_reflects(tmp_path):
    w = _world(tmp_path)
    for h in range(5):
        w.step(float(h))
    assert w._step_social == [], "step 步末必须清空社交队列"
    a = w.npc("A")
    obs = a.store.all_valid(player_id="B", types=["observation"])
    assert obs, "A 应观察到新出现的 B"
    assert a._reflected_obs.get("B", 0) > 0, "full 档新观察应触发关系反思"
    assert a.store.all_valid(player_id="B", types=["reflection"]), \
        "关系反思应实际落库"
    w.close()
