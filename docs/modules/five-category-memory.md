# 五类记忆组织

状态：记忆存储侧已实现并验证；NPC 接入待实施。日期：2026-11-05。
关联：[记忆存储](memory.md)、[分层访问](tiered-memory.md)、[NPC 编排](npc-runtime.md)、[包入口](package-api.md)。

## 1. 目标与范围

在现有两库上提供人格核心、当前状态、长期语义记忆、情节记忆、原文档案五类组织。沿用原记忆类型、证据 ID、评分、原文和默认上下文路径。本轮不增加事实自动提取、情绪/承诺自动维护、向量持久化、统一生成上下文或防 OOC 判定，不宣称真实角色稳定性已提高。

## 2. 当前实现

人格目前由 NPC 名称与可变 persona_traits 表示，运行状态与 PlanState 归 NPC；主库以 observation/reflection/plan/episode/identity 区分记录，档案库保存来源及事件。尚无统一五类入口；L1/L2/L3 描述访问策略，不表示这五类认知职责。

## 3. 目标设计与所有权

| 类别 | 标识 | 当前数据映射 | 所有者 |
|---|---|---|---|
| 人格核心 | persona_core | PersonaProfile：姓名、人格数值、背景、价值观、底线、表达风格、长期动机、版本 | NPC 显式配置；保存到现有 npc 元数据 |
| 当前状态 | current_state | 有效 plan 记录 + NPC 当前时钟、档位、计划块、当前活动与中断说明 | NPC/PlanState；读取为副本 |
| 长期语义记忆 | semantic | reflection、identity | 原反思组件写入主库；identity 是可修正自我认知，不是权威人设 |
| 情节记忆 | episodic | observation、episode | 原观察/固化组件写入主库 |
| 原文档案 | raw_archive | 原档案事件引用及其原文 | 每 NPC 独立档案库 |

`MemoryCategory` 为上述五值枚举。`MemoryRecord.category` 是计算属性，不加入 dataclass 字段，不改变 asdict、SQLite 或旧检索 JSON；未知自定义 type 返回 None，不随意归类。

`organization.py` 提供纯数据契约，无 NPC/数据库/模型依赖。MemoryStore 负责有界分类读取，NPC 补齐人格和运行状态；不把 NPC 引入存储层。不复制权威世界状态，不凭空补全情绪、任务或承诺。

## 4. 存储与兼容

不新增数据库、表或记忆字段；旧数据按类型映射即可分类。PersonaProfile 为不可变结构，复制并只读包装人格数值，序列化使用显式 to_dict/from_dict。默认从旧名称和 persona_traits 构造，描述字段为空；不利用自动 identity 反向补人设。

旧 persona_traits 的可变 API 保留，PersonaProfile 读取反映其当前数值；本轮不将旧 API 宣称为不可修改的人格锁。新背景等字段通过显式 set_persona_profile 修改，要求同 NPC 名称；显式更新数值时原地更新 persona_traits，保持既有组件引用。新配置不同于旧配置时须增加版本。反思、遗忘、合并均无人格配置写入权限。

NPC.save 在原 npc 元数据键中增加可选 persona_profile，保留四个元数据键的写入顺序；load、独立 checkpoint_state/from_checkpoint 同时覆盖新配置。旧存档缺失字段时按旧人设构造；两个库仍需配对备份。save/load 原有运行状态恢复边界不扩张。

## 5. 对外接口与范围契约

- `MemoryStore.organize(scope: EventScope, limit=32)` 返回 `MemoryContents`，包含 current_state/semantic/episodic 记录元组和 raw_archive 事件引用元组；各类别分别限量，范围为 1–128，拒绝 bool。SQL 按时间和 id 倒序筛选有效、非未来、当前关系及可选共享流记录，不更新访问时间，不调用模型或嵌入。
- 默认 EventScope 的 player_id=None 表示只读共享流，保持事件接口语义，不采用 all_valid(None) 的全流语义。
- 档案引用沿用 query_events(scope, descending=True) 的权限、实例、时间和顺序；未指定 instance_id 时沿用现有“不按实例过滤”语义。原文仍需 read_event_source(ref.source_id, scope) 显式读取，避免整批加载超长原文。
- 主库旧记录没有实例字段；指定 instance_id 时三个派生类别返回空，只返回该实例授权档案。不能将全局主库记录冒充本局记录。
- `NPC.memory_categories(scope=None, limit=32)` 返回 `NPCMemory`，五个字段为 persona_core/current_state/semantic/episodic/raw_archive。省略 scope 时使用 NPC 当前时钟的共享范围。指定 scope 时仅允许 as_of 等于当前 NPC 时钟；过去时点的记录通过 store.organize 读取，不把当前人格/运行态伪装成历史快照。实例 scope 不带入旧空间计划活动。
- 当前状态提供分类的 plan 记录以及 NPC 的运行计划。运行计划来自 NPC 本身，不推断第三方状态。返回集合与记录均不暴露可写数据库对象。
- 新名称仅从 game_agent.memory 按需导出；根包现有导出不变。原 L1/L2/L3 及三条生成出口保持原行为，本入口是组织与读取能力，不是新生成策略。

## 6. 实施顺序

1. 先更新本设计及关联模块契约。
2. 记忆模块：纯数据类型、类型分类、SQL 有界读取、MemoryStore 门面、公开导出及测试，验证后独立提交。
3. NPC 模块：人格配置、五类组合、原元数据和完整检查点往返、旧存档兼容及测试，验证后独立提交。
4. 更新使用入口与实现状态；不纳入未跟踪的 interview_deck/。

## 7. 验收与证据

存储侧：`test_memory_organization`、`test_memory_repository`、`test_memory_ranking`、`test_memory_archive`、`test_module_dependencies` 共 **129 项通过**。覆盖五类类型映射及未知类型、原序列化不变、不可变人设与 JSON 往返、无模型只读查询、SQL 限量与稳定顺序、关系/共享/未来/失效/实例隔离、返回副本及旧两库重开。新进程验证五类公开类型不加载 SQLite 或 NPC。`git diff --check` 通过。

待验证 NPC 接入：人设版本及显式更新、反思不覆盖核心、旧库、新配置和两库检查点往返，以及完整 Python 离线测试。不改前端，不运行真实模型或在线质量评测。

## 8. 未决问题与后续

自动语义事实及时间版本、情绪/承诺状态、实例派生记忆、角色成长策略、统一 prompt 及 OOC 检查均另行设计。五类组织完成不代表这些能力已实现。
