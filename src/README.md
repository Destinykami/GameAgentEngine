# 源码目录

正式包为 `game_agent`，开发新代码时使用该包及其模块目录：

| 目录 | 负责的内容 |
|---|---|
| `game_agent/cognition/` | NPC 编排、反思、规划、反应、对话和自治决策 |
| `game_agent/memory/` | 记录模型、检索排序、维护策略、SQLite 仓储与门面 |
| `game_agent/world/` | 实体、感知、动作、事件、社交、扩展规则和世界运行 |
| `game_agent/models/` | LLM / 向量接口、哈希向量和兼容 HTTP 适配 |
| `game_agent/evaluation/` | 集成探针；导入不会执行真实 API 检查 |

公共用法为 `from game_agent import NPC, World`。`src` 是源码根目录，不是包名；安装及设计规则见根 README 和 `docs/source-layout.md`。

`game_agent/cognition/reflection/` 内按生成编排（`engine.py`）、写入规则（`writing.py`）、冲突处理（`conflicts.py`）、窄接口（`contracts.py`）与阈值词表（`policies.py`）组织，公共入口保持 `from game_agent.cognition.reflection import ReflectionEngine`。

`game_agent/cognition/planning/` 内按生成编排（`engine.py`）、时间规则（`rules.py`）、规划记忆（`memory.py`）、计划状态（`state.py`）与窄接口（`contracts.py`）组织；NPC 通过 `PlanState` 管理当前计划，公共引擎入口保持 `from game_agent.cognition.planning import PlanningEngine`。

`game_agent/cognition/dialogue/` 内按单轮生成（`engine.py`）、上下文准备（`context.py`）、双人轮流（`exchange.py`）与窄接口（`contracts.py`）组织，公共入口保持 `from game_agent.cognition.dialogue import DialogueManager`；对话观察写入仍由 NPC / World 负责。
