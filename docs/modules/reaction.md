# 事件反应、效用策略与关系信任

状态：已实现并通过离线行为、导入及安装验证。最后核对日期：2026-10-23。
实现入口：`src/game_agent/cognition/reacting/`，ReactionDecider / ReactionDecision 的正式导入方式保持可用。
关联设计：[决策与自治输入](decision.md)、[NPC 编排](npc-runtime.md)、[记忆](memory.md)。

## 1. 目标与职责边界

事件反应按事件价值、当前计划、人格和关系信任判断接受或婉拒；关系信任独立负责关系流取证、模型判断与签名缓存。将纯效用规则、事件评分缓存和信任缓存分开，通过窄接口访问模型与记忆。

NPC 继续拥有时钟、当前计划上下文和完整反应缓存；World 继续拥有自治动作的调度与执行。事件反应不与 autonomous.py 合并，不修改用户已确认的自治多对象记忆边界。记忆模块继续负责 SQLite、有效记忆及绝对重要性检索权重。

## 2. 重构前实现

`ReactionDecider` 同时负责关系取证、信任模型调用、信任缓存、事件模型调用、LRU、效用公式及返回文字，并直接依赖 MemoryStore / LLMClient。NPC.react 在完整决策缓存查找之前取信任，用其量化档位构造缓存键；直接调用 decider.decide 时则先评分、再查询信任。

现有实际规则必须保留：事件缓存键不含人格；信任签名不含内容、置信度、importance 或单条 id；信任缓存无条数上限；无记忆时中性返回不删除旧缓存。现有注释对“签名未变即置信度未变”的描述不是所有公开记忆修改路径的保证，本次不据此增强或更改签名。

## 3. 已实现设计

```text
cognition/reacting/
├── __init__.py  # 按需导出既有 ReactionDecider / ReactionDecision / 常量
├── engine.py    # ReactionDecider：评分 → 可选信任 → 纯策略，协调缓存清理
├── scoring.py   # EventScorer：事件评分与 256 条 LRU
├── trust.py     # RelationshipTrust：关系取证、判断及实例独有签名缓存
├── policy.py    # ReactionDecision 和纯效用 / 返回文本规则
└── contracts.py # 事件评分、信任判断和关系记忆的窄接口
```

编排器 → 评分组件 / 信任组件 / 纯策略；信任组件 → 关系记忆端口 / 信任模型端口；评分组件 → 事件模型端口。组件不获取 NPC、World 或数据库连接。纯策略不调用模型、记忆或缓存。

## 4. 数据与状态归属

| 数据 / 状态 | 所有者 | 生命周期 |
|---|---|---|
| 事件价值 `(social, goal, interruption)` | EventScorer | 每个 decider 独立缓存，键为 `(event, current_plan)`；LRU 上限 256 |
| 玩家 → `(trust, signature)` | RelationshipTrust | 每个 decider 独立普通 dict，无新增上限或自动淘汰；不持久化 |
| 关系调制开关 | ReactionDecider | 保留构造参数及只读 use_relationship 属性 |
| 完整 ReactionDecision 缓存 | NPC | 原 512 上限、信任量化、计划前 20 字键及清理方式不变 |
| 关系记忆 | 记忆模块 | 只读 all_valid，不刷新访问时间、不按 importance 排序 |

## 5. 对外契约

- `ReactionDecider(store, llm, use_relationship=True)`、`decide(...)`、`relationship_trust(...)`、`clear_cache()` 和只读 `use_relationship` 保持原用法。
- `ReactionDecision` 四个字段、可变 dataclass 行为、位置参数和返回文字保持原样。
- 新增只读诊断 `cache_sizes()`，返回新的 `{"events": 数量, "trust": 数量}`，不暴露可变缓存对象；组件提供 cache_size 属性。原测试迁移到此接口，不保留 `_value_cache` / `_trust_cache` 兼容代理。
- EventScorer 仅需模型 `score_event`；RelationshipTrust 仅需记忆 `all_valid(player_id=...)` 和模型 `judge_trust`；无继承要求。
- NPC 的 react / trust_toward / clear_cache 业务流程及公开方法保持不动。

## 6. 流程与不变式

- 直接 decide 先取得并解包三项事件评分，再按开关查询信任，最后执行纯效用规则。无效评分形状仍在信任查询之前报错，已缓存的返回值不回滚。
- 开关关闭时不查询关系记忆、不调用 judge_trust；社交信任调制固定 1，返回文字中的信任按原样为 0。直接 relationship_trust 查询不受该开关限制。
- 公式保持 `social_weight = persona.social(default 0.5) * max(0, 1 + trust)`、`goal_weight = persona.goal_oriented(default 0.5)`、`U = social_weight * social_value + goal_weight * goal_value - interruption_cost`；`U >= 0` 接受。不新增 trust / 人格 / 评分裁剪或有限值检查。
- player_id=None 直接返回 0，不查库。无有效关系记忆也返回 0，不调用模型、不删除旧信任缓存。
- 签名由全部有效关系记忆的条数与最大时间戳决定，包括未进入取证窗口的类型。命中保持原信任，不因置信度 / 内容单独修改而自动重判。
- 证据分两池：reflection / identity / episode 最新 10 条在前，observation 最新 20 条在后；每池按 `(timestamp, id or 0)` 降序稳定排序。不用一池的空位补另一池，不以 importance 加权。只含 plan 等其他类型的非空关系流仍调用 judge_trust，传入空证据。
- 每项证据传原 `(type, content, confidence)`，传闻仅按原文本加 `[传闻N跳] ` 前缀。不改变亲见 / 传闻权重、信任随遗忘的规则或模型提示词。
- 事件缓存命中刷新 LRU，零值也命中；人格变更不额外触发同键重评。模型抛错不写入对应缓存；评分成功但后续信任失败时保留已完成的评分缓存。
- clear_cache 先清事件缓存，再清信任缓存；NPC 同时清其完整反应缓存。缓存不跨实例、不持久化。
- 模型原返回值原样传递与缓存，异常不吞并、不重试。此处不增加修复或优化策略。

## 7. 配置与成本

保留 JUDGE_TRUST_MAX_MEMORIES=30、EVENT_VALUE_CACHE_LIMIT=256 及既有开关。一次事件评分 miss 调用一次 score_event；一次非空关系签名 miss 调用一次 judge_trust。无新增检索、嵌入、网络请求、日志或后台任务。

## 8. 实施步骤

1. 保存旧 reacting / NPC 实现和 16 步确定性时间线。
2. 提取纯策略、评分、信任及窄接口，将同名模块整理为职责子包。
3. 保留 NPC 业务流程，测试通过只读诊断检查清理与上限，移除对 decider 私有字段的访问。
4. 用既有测试与新增端口 / 窗口 / 失败 / 缓存用例验收；对照原实现的输入、结果、调用和缓存状态。
5. 验证独立导入、安装和时间线，回写结果并单独提交。

## 9. 验收与证据

| 要求 | 验证 | 结果 |
|---|---|---|
| 关系隔离、置信度 / 传闻输入、成本和消融行为 | 复用信任、缓存、计划反应、消融、社交和持久化测试 | 332 个离线测试通过（3.80s） |
| 窄接口、固定窗口、缓存失效边界及失败顺序 | 新增组件行为用例 | 11 个新增用例通过：效用边界、取证顺序与配额、签名、实例隔离、LRU、失败重试、诊断隔离和消融 |
| 无运行时 / SQLite / HTTP 依赖 | 新进程导入隔离 | 6 个新增子包 / 组件导入隔离用例通过 |
| 保持原行为 | 原 decider / NPC 对照及 16 步时间线 | 16 组配置的 224 个直接决策检查点、5 个 LRU 检查点、72 个 NPC 检查点相同；评分、信任及效用 / 文本核心归一缓存字段后 AST 一致；NPC 源码未改；16 步时间线相同 |
| 正式安装 | 仓库外编辑安装和独立 wheel 安装 | 两种安装均通过公开入口、SQLite 关系读取、决策与缓存清理检查；wheel 含 6 个新模块，不含旧 reacting.py 或 persona_agent 包 |
| 文档一致性 | 当前文档本地链接与差异检查 | 24 份文档本地链接和 git diff --check 通过 |

对照覆盖启用 / 关闭关系调制、空关系 / 只有计划、高阶和观察窗口、传闻、置信度、非标准模型返回值、评分 / 信任失败、人格与记忆原地变更、签名变化、缓存刷新淘汰及清理、NPC 计划上下文、认知档位和 SQLite 保存重载。

真实 API 不可达，仅使用离线替身；不运行真实模拟、探针、在线评测或前端构建，不新增真实模型效果结论。

## 10. 未决问题

当前职责和保留行为均可由代码确定，无必须询问的未决项。增强信任签名、给事件缓存加入人格键、设置新信任缓存上限或改变证据分配均属于行为修改，未纳入本次重构。
