"""仓储上下文保证插入与维护失败不会留下半条记忆。"""

import pytest

from game_agent import MemoryRecord, MemoryStore
from game_agent.models.embeddings import HashEmbedder
from game_agent.memory.repository import MemoryRepository


class _FailingEmbedder(HashEmbedder):
    def embed(self, texts):
        raise RuntimeError("向量编码失败")


def test_failed_embedding_rolls_back_memory_insert(tmp_path):
    path = str(tmp_path / "npc.db")
    store = MemoryStore(_FailingEmbedder(), path)
    try:
        with pytest.raises(RuntimeError, match="向量编码失败"):
            store.add(MemoryRecord("无法编码的记录", 0.0))
        assert store.count() == 0
        assert store._vec_cache == {}
    finally:
        store.close()
    restored = MemoryStore(HashEmbedder(), path)
    try:
        assert restored.count() == 0
    finally:
        restored.close()


def test_failed_observation_edit_keeps_persisted_state(tmp_path):
    repository = MemoryRepository(str(tmp_path / "npc.db"))
    try:
        with repository.insert(MemoryRecord("原观察", 0.0, importance=5.0)) as mid:
            pass
        with pytest.raises(RuntimeError, match="维护中断"):
            with repository.edit_observation(mid) as rec:
                rec.content = "未提交的新内容"
                rec.importance = 9.0
                rec.last_accessed = 6.0
                raise RuntimeError("维护中断")
        restored = repository.all_valid()[0]
        assert restored.content == "原观察"
        assert restored.importance == 5.0
        assert restored.last_accessed is None
    finally:
        repository.close()
