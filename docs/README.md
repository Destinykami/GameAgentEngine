# 项目设计文档

本目录用于按模块维护设计，再依据设计修改代码。自治决策保持共享记忆与全部可见关系面；记忆评分采用绝对 `importance / 10`。两项设计均已获用户确认。

## 阅读入口

| 文档 | 用途 | 状态 |
|---|---|---|
| [系统总览](architecture.md) | 当前实现、运行链路、模块边界与主要问题 | 已按 2026-10-23 代码核对 |
| [重构与验收](refactoring.md) | 实施范围、提交记录、保留行为与验收证据 | 本轮结构重构及离线验收已完成 |
| [正确性与可靠性加固计划](reliability-plan.md) | 审查问题、分阶段修改范围、验收标准与提交安排 | A–E 已完成，453 个离线测试 / 10 个前端测试 / 102 项浏览器断言通过 |
| [模块设计模板](templates/module-design.md) | 后续每个模块蓝图的统一格式 | 可直接使用 |
| [源码布局与包命名](source-layout.md) | src 布局、模块目录、安装与导入契约 | 已实现并移除旧包兼容层，280 个离线测试通过 |

模块蓝图均已落盘，实施状态见下表；接口、状态归属、保留行为和验证证据记录在各设计中。总览描述当前实现，原历史材料继续保留。

## 模块实施记录

2026-10-25 新工作：[分层记忆与每 NPC 独立原文档案](modules/tiered-memory.md) 的存储、NPC、对话、模型适配和持久化已分模块提交。Python 离线全集 481 项通过、6 项真实端点探针跳过；离线 wheel 独立安装、两库检查点恢复通过。额外的关系反思窗口调整已向用户提问，确认前保留旧行为。下表保留各模块历史验收，不代表最新测试数量。

| 模块蓝图 | 状态 | 实现入口 |
|---|---|---|
| [世界实体与空间模型](modules/world-model.md) | 已实现，246 个离线测试通过 | `src/game_agent/world/entities.py` |
| [结构化事件契约](modules/events.md) | 已实现，246 个离线测试通过 | `src/game_agent/world/events.py` |
| [世界持久化](modules/persistence.md) | 已实现，247 个离线测试通过 | `src/game_agent/world/persistence.py` |
| [NPC 认知编排边界](modules/npc-runtime.md) | 编排收尾已拆分，354 个离线测试通过 | `src/game_agent/cognition/npc/` |
| [空间感知与距离调度](modules/perception.md) | 已实现，247 个离线测试通过 | `src/game_agent/world/perception.py` |
| [包入口与依赖加载](modules/package-api.md) | 已实现，251 个离线测试通过 | `src/game_agent/__init__.py` |
| [决策与关系记忆边界](modules/decision.md) | 自治边界已实现，255 个离线测试通过；事件反应另见专项蓝图 | `src/game_agent/cognition/autonomous.py` / `src/game_agent/cognition/reacting/` |
| [场景效果与行为链](modules/world-extensions.md) | 已实现，256 个离线测试通过 | `src/game_agent/world/extensions.py` |
| [社交观察与传闻路由](modules/social.md) | 已实现，257 个离线测试通过 | `src/game_agent/world/social.py` / `src/game_agent/world/social_contracts.py` |
| [动作执行](modules/actions.md) | 已实现，258 个离线测试通过 | `src/game_agent/world/actions.py` |
| [记忆模块](modules/memory.md) | 已拆分，275 个离线测试通过 | `src/game_agent/memory/store.py`、`src/game_agent/memory/models.py`、`src/game_agent/memory/ranking.py`、`src/game_agent/memory/policies.py`、`src/game_agent/memory/repository.py` |
| [反思模块](modules/reflection.md) | 已拆分，291 个离线测试通过 | `src/game_agent/cognition/reflection/` |
| [规划模块](modules/planning.md) | 已拆分，303 个离线测试通过 | `src/game_agent/cognition/planning/` |
| [对话模块](modules/dialogue.md) | 已拆分，315 个离线测试通过 | `src/game_agent/cognition/dialogue/` |
| [事件反应与关系信任](modules/reaction.md) | 已拆分，332 个离线测试通过 | `src/game_agent/cognition/reacting/` |
| [源码布局](source-layout.md) | 已迁移并移除旧包兼容层，280 个离线测试通过 | `src/game_agent/`、`pyproject.toml` |
| [模型接入与输出解析](modules/model-adapters.md) | 已拆分，372 个离线测试通过 | `src/game_agent/models/llm_http/`、`config.py`、`transport.py`、`embeddings_http.py` |
| [世界循环与公开编排](modules/world-runtime.md) | 组件已提取，场景查询边界已收尾 | `src/game_agent/world/runtime.py` |
| [稻妻场景与运行产物](modules/scenarios.md) | 已拆分，395 个离线测试通过 | `src/game_agent/scenarios/inazuma/`、`src/game_agent/runners/` |
| [评测场景与指标](modules/evaluation.md) | 已拆分，410 个离线测试通过 | `src/game_agent/evaluation/`、`evals/fixtures/`、`evals/experiments/` |
| [回放与可视化](modules/visualization.md) | 已拆分，417 个 Python 测试、5 个前端测试及 98 项浏览器断言通过 | `visualization/src/replay/`、`visualization/src/scenes/`、`src/game_agent/runners/replay/` |

当前累计验证（2026-10-25）：453 个 Python 离线测试通过，6 个真实探针默认跳过；10 个前端离线测试及 102 项浏览器断言通过；TypeScript/Vite 构建及时间线数据校验通过。此前模块的原实现对照记录保留在相应蓝图中。各行测试数为该模块提交时的记录；未运行真实模型、真实模拟或在线评测。

## 当前范围与验证约束

用户已确认：真实模型 API 目前不可达。结构重构后已授权按可靠性计划进行缺陷修正，信任缓存精度、保存失败策略、独立检查点及直播异常策略均已确认；行为变化与验收见加固计划。

- 按模块先写设计，再实现结构、职责、接口与依赖调整，保持现有行为契约。
- 使用离线 stub / fake 模型、确定性时间线、保存恢复测试及适用的前端检查验收。
- 当前不运行真实模型模拟、真实模型探针和依赖真实端点的评测；这些项目不作为重构完成的前置条件。
- 保留真实模型适配、调用契约、提示词及评测入口；离线验证不产生新的真实模型效果结论。
- 模型服务部署与恢复、新玩法及策略效果优化不属于当前范围。

## 设计与代码的协作规则

1. 修改模块前，先建立或更新对应蓝图，说明目标、边界、输入输出、状态和验收条件。
2. 每份蓝图明确区分**当前实现**、**目标设计**和**未决问题**。建议稿不代表代码已经实现。
3. 设计涉及其他模块时，同步检查接口契约、状态归属及相关蓝图。
4. 实现完成后更新状态、代码映射与验证结果；发生设计偏差时回写原因。
5. 行为变化单独标注，避免把行为修改混进文件拆分；每一步保留可运行、可验证的结果。
6. 通用引擎、具体场景、展示和评测分别描述。文档按职责组织，不机械地为每个源文件建立一份设计。
7. 每个模块完成蓝图、实现与离线验证后单独提交 Git。提交正文写明模块边界、代码改动、兼容策略、验证结果与未运行项；仅暂存该模块相关文件。
8. 遇到影响职责归属、行为语义或对外契约且无法从现有设计确定的问题，暂停相关重构并询问用户。

## 原有文档的衔接

- [README](../README.md)：保留使用入口与现有实现说明。
- [OVERVIEW](../OVERVIEW.md)：原有系统总览，包含历史状态与验证结论。
- [WorldPlan](../WorldPlan.md)、[AutoSimPlan](../AutoSimPlan.md)、[NextPlan](../NextPlan.md)：原有世界层、自治模拟及后续功能计划。
- [VisualizationPlan](../VisualizationPlan.md)、[EvalPlan](../EvalPlan.md)：原有可视化与实验计划。
- [REVIEW](../REVIEW.md)、[ReviewFixPlan](../ReviewFixPlan.md)：历史审查及修复记录。

这些文档本轮保留在原位。后续按模块提取仍有效的设计，核对代码后合并到新蓝图；历史审查记录保留上下文，新增入口链接，避免一次搬迁破坏已有引用。
