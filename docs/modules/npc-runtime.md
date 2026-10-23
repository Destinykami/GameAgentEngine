# NPC 认知编排与公开边界

状态：与实现一致（运行状态与关系反思门控已封装）。核对日期：2026-10-23。

## 职责与状态所有权

NPC 负责认知组件组装、记忆写入、认知档位、反思触发、缓存及自身保存恢复，并持有规划模块的 PlanState。World 负责空间可见性和生命周期调度，不应读写 NPC 的私有档位、关系反思水位或记忆筛选实现。

组件仍由 NPC 持有；本次不重写 MemoryStore、ReflectionEngine、PlanningEngine、ReactionDecider 或 DialogueManager。两条决策路径继续保留原行为。

后续[反思模块重构](reflection.md)已将生成、写入和冲突职责分开；此处的 NPC 触发阈值、水位、共享冲突签名和调用顺序保持不变。

后续[规划模块重构](planning.md)已统一计划块、中断兜底和当前活动查询的归属。NPC 通过 `plan_state` 替换状态和保存快照；仍在原时机推进时钟、调用规划及响应异常，`plan_blocks` 保存键和中断兜底不持久化的行为保持不变。

后续[对话模块重构](dialogue.md)已分离上下文、单轮生成和独立轮流工具。NPC.speak 仍按原顺序推进时钟、关系反思、生成回复和可选记录来话 / 回复；双人轮流工具不接管这条记忆回流链路，World 的防重复参数保持不变。

## 本次公开接口

| 接口 | 契约 |
|---|---|
| `tier` 只读属性 | 获取认知档位；修改仍经 `set_tier` |
| `maybe_reflect_relationship(entity_id, now)` | 仅 full 且观察数量增加时反思；成功后更新水位，失败保留旧水位并向调用方传播异常 |
| `decision_context(visible_entities)` | 只返回共享流及指定可见实体的关系记忆，保持原插入顺序取末 5 条并拼接 |
| `has_relationship(entity_id)` | 查询当前对象是否存在有效关系记忆，不暴露内部记录 |
| `identity_belief()` | 返回最新有效共享身份信念文本，无记录返回空串 |

`speak` 与 `World.flush_social` 复用同一个关系反思门控，消除重复实现。门控本身不新增时钟推进；已有调用顺序、异常传播和水位保存键不变。

World 仍决定哪些实体可见、何时注入身份信念和何时调用关系反思；NPC 不获取整个世界对象。信任查询复用已有 `trust_toward`，World 不直接调用 NPC 的 decider。

## 验收

复用对话隐私、自治决策隔离、社交水位、反思失败隔离、档位和运行状态恢复测试。验证离线全集及 16 步确定性时间线；World 不再访问 `_tier` 或 `_reflected_obs`。真实模型验证不在本阶段范围内。

验证结果：247 个离线测试通过（3.50s）；16 步确定性时间线不变；`git diff --check` 通过。示例与调度评测的档位读取已迁移到 `tier` 属性。
