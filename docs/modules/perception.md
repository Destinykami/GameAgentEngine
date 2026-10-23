# 空间感知与距离调度

状态：与实现一致。核对日期：2026-10-23。

## 边界

新增 `persona_agent/perception.py`。模块只依赖实体模型与标准库，负责可见实体筛选、最近存活玩家距离对应的档位、在场变化检测及观察文本生成。

World 仍拥有实体和认知对象注册表、半径及功能开关，负责应用档位和把社交交互加入待反思队列。感知模块不获取 World 对象、不访问 NPC 私有字段、不查询记忆库，也不直接调用模型。

## 接口与状态

- `visible_entities(observer, entities, radius)` 返回范围内、非自身、存活的实体，保持输入顺序。
- `cognitive_tier(observer, entities, full_radius, perception_radius)` 保留 full / compressed / idle 边界；死亡观察者返回 idle。强制 full 的实验开关仍在 World 应用。
- `PresenceTracker.perceive(...)` 通过只含 name / tier / observe 的认知端口写入观察，并通过 `on_social(entity_id)` 通知 World 登记社交交互。
- `PresenceTracker` 独占玩家出现状态和 NPC 出现集合，每个 World 创建一个独立实例。这些状态继续仅存在内存中，不增加保存恢复行为。

## 行为契约

默认玩家感知仍逐次产生观察，由 NPC 去重；玩家过渡开关打开时，位置或档位不变则跳过。社交感知仅对新出现的 NPC 产生观察，按名字排序；离开再出现可重新触发。

观察顺序、文本、半径等号、死亡与 idle 早退及失败时状态更新顺序均保持现状。半径依旧由 World 每次传入，运行中修改半径不会被新模块缓存。

## 验收

复用空间感知、档位边界、死亡实体、玩家过渡、社交在场与成本测试；离线全集通过，确定性时间线保持不变。真实模型验证不在本阶段范围内。

验证结果：247 个离线测试通过（3.59s）；16 步确定性时间线不变；`git diff --check` 通过。
