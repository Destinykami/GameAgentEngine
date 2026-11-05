# 历史文档归档

本目录收录从仓库根目录迁入的 8 份历史文档（归档日期：2026-11-05），用于追溯早期设计、实施与审查过程。文件名保持不变；下表“原位置”均相对于仓库根目录。

**当前实现以[设计文档入口](../README.md)及其模块设计为准。** 归档不表示所有历史计划均已完成，也不表示历史测试数、实验结论和部署状态适用于当前版本。根目录保留项目首页与协作工具入口：`README.md`、`AGENTS.md`、`CLAUDE.md`。

## 总览

| 文档 | 原位置 | 历史用途 | 当前入口 |
|---|---|---|---|
| [系统总览](OVERVIEW.md) | `OVERVIEW.md` | 早期人格、关系、记忆和验证体系总览 | [系统架构](../architecture.md)、[源码布局](../source-layout.md) |

## 实施与评测计划

| 文档 | 原位置 | 历史用途 | 当前入口 |
|---|---|---|---|
| [世界层实施计划](WorldPlan.md) | `WorldPlan.md` | 空间世界、距离感知及调度的分阶段实施 | [世界运行](../modules/world-runtime.md)、[空间感知](../modules/perception.md) |
| [多智能体自治世界](AutoSimPlan.md) | `AutoSimPlan.md` | 自主行动、场景规则与自治仿真计划 | [决策](../modules/decision.md)、[场景](../modules/scenarios.md) |
| [项目演进计划](NextPlan.md) | `NextPlan.md` | 社交、固化、关系阶段与低成本自治路线 | [社交](../modules/social.md)、[记忆](../modules/memory.md)、[事件反应](../modules/reaction.md) |
| [可视化计划](VisualizationPlan.md) | `VisualizationPlan.md` | 稻妻空间回放的原始里程碑与契约 | [可视化设计](../modules/visualization.md)、[使用说明](../../visualization/README.md) |
| [三实验评测计划](EvalPlan.md) | `EvalPlan.md` | 记忆一致性、决策消融与调度效率的设计 | [评测设计](../modules/evaluation.md)、[方法与历史结果](../../evals/README.md) |

## 审查与修复记录

| 文档 | 原位置 | 历史用途 | 当前入口 |
|---|---|---|---|
| [早期代码审查](REVIEW.md) | `REVIEW.md` | 记忆、反思、规划等模块的问题与修复记录 | [记忆](../modules/memory.md)、[反思](../modules/reflection.md)、[规划](../modules/planning.md) |
| [审查修复实施计划](ReviewFixPlan.md) | `ReviewFixPlan.md` | 2026-10-18 审查后的 P0/P1/P2 修复与验收 | [重构记录](../refactoring.md)、[可靠性加固](../reliability-plan.md) |

## 阅读与维护约定

- 归档正文保留旧包名、历史命令、测试数量和状态，不据此推断当前 API、服务连通性或模型效果。
- 指向已删除 `persona_agent/` 源码的链接已改为保留原路径和行号的代码文本，可结合 Git 历史追溯；不会伪造与当前源码的行号映射。
- 文档之间的相对链接及回到现有使用说明的链接已按归档位置调整。仓库外的旧根目录链接不自动重定向，可通过本索引定位。
- 新设计继续写入 `docs/modules/`；只有历史材料进入本目录。归档实施与验证见[文档组织与历史归档](../modules/documentation.md)。
