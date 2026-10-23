# 源码目录

正式包为 `game_agent`，开发新代码时使用该包及其模块目录：

| 目录 | 负责的内容 |
|---|---|
| `game_agent/cognition/` | NPC 编排、反思、规划、反应、对话和自治决策 |
| `game_agent/memory/` | 记录模型、检索排序、维护策略、SQLite 仓储与门面 |
| `game_agent/world/` | 实体、感知、动作、事件、社交、扩展规则和世界运行 |
| `game_agent/models/` | LLM / 向量接口、哈希向量和兼容 HTTP 适配 |
| `game_agent/evaluation/` | 纯指标、结果格式、显式运行依赖与真实探针；导入不检查端点 |
| `game_agent/scenarios/` | 具体场景的人物、地图、规则、裁决和故事顺序 |
| `game_agent/runners/` | 显式运行入口、时间推进、终端输出及 JSON/JSONL 产物 |

公共用法为 `from game_agent import NPC, World`。`src` 是源码根目录，不是包名；安装及设计规则见根 README 和 `docs/source-layout.md`。

`game_agent/cognition/reflection/` 内按生成编排（`engine.py`）、写入规则（`writing.py`）、冲突处理（`conflicts.py`）、窄接口（`contracts.py`）与阈值词表（`policies.py`）组织，公共入口保持 `from game_agent.cognition.reflection import ReflectionEngine`。

`game_agent/cognition/planning/` 内按生成编排（`engine.py`）、时间规则（`rules.py`）、规划记忆（`memory.py`）、计划状态（`state.py`）与窄接口（`contracts.py`）组织；NPC 通过 `PlanState` 管理当前计划，公共引擎入口保持 `from game_agent.cognition.planning import PlanningEngine`。

`game_agent/cognition/dialogue/` 内按单轮生成（`engine.py`）、上下文准备（`context.py`）、双人轮流（`exchange.py`）与窄接口（`contracts.py`）组织，公共入口保持 `from game_agent.cognition.dialogue import DialogueManager`；对话观察写入仍由 NPC / World 负责。

`game_agent/cognition/reacting/` 内按反应编排（`engine.py`）、评分与 LRU（`scoring.py`）、关系信任（`trust.py`）、纯效用及返回数据（`policy.py`）与窄接口（`contracts.py`）组织，公共入口保持 `from game_agent.cognition.reacting import ReactionDecider, ReactionDecision`。

`game_agent/cognition/npc/` 内按编排与组装（`engine.py`）、运行状态（`state.py`）、观察（`observation.py`）、固化（`consolidation.py`）、完整反应缓存（`reactions.py`）、只读记忆视图（`context.py`）、元数据保存恢复（`persistence.py`）及窄接口（`contracts.py`）组织。公共入口保持 `from game_agent import NPC`；公开时钟、运行状态副本与缓存数量供调用方诊断。

`game_agent/models/llm_http/` 分开客户端组装、按任务组织的提示词、输出解析、传输重试与用量统计；连接默认值与实例参数在 `models/config.py`，单次 JSON POST 在 `models/transport.py`。向量适配器保留独立响应与回退规则。正式 RealLLM / RealEmbedder 导入不变。

`game_agent/runners/replay/` 分开终端文本与节奏、静态 HTML 模板和 JSON/CLI 分发。`visualization/src/replay/` 管浏览器投影、事件、输入及直播；两种回放只读取时间线，不启动模型。
