# 通用记忆事件与组合查询

状态：存储、查询和 NPC 元数据接入已实现并完成离线验收。设计日期：2026-10-25。
关联设计：[分层记忆](tiered-memory.md)、[NPC 编排](npc-runtime.md)、[展示事件](events.md)。

## 目标与边界

维护每个 NPC 自己获知的事件及证据，供不可预先枚举的历史问题组合查询。不增加见面编号、道歉次数等问题专用字段；不把世界全局日志自动变成 NPC 知识。原文仍完整保存在各 NPC 的独立档案库，摘要、反思和索引不能替代原文。

现有档案已有稳定原文 ID、入库顺序、关系流、时间、发言者、片段全文索引和来源映射，但没有统一事件上下文或通用查询契约。本轮添加事件索引，不改原文及主库记忆评分，不引入新的模型调用或自动历史检索路径。自然语言查询规划器、事实版本管理、物理压缩及大规模性能调优留待后续。

## 数据与不变式

- 每条原文对应一条事件索引，事件 ID 直接使用原文 ID；原文不复制到事件表。原文、事件、参与者、全文片段及 pending 同事务写入，派生失败仍可查询。
- `EventContext` 提供开放的事件类型、实际发生时间 `occurred_at`、行为者、目标、参与者、地点以及证据性质。获知时间 `observed_at` 由写入参数 now 确定；现有 source.timestamp 继续表示写入所处的游戏时间，不改变主库来源绑定。
- 证据性质区分 utterance、observation、report、action_attempt、derived、legacy_snapshot 和 unclassified。收到动作尝试不等于物理动作成功；玩家说过的话不自动等于事实。传闻发生时间未知时不使用听说时间替代。
- 时间单位均为游戏小时。原文顺序是本 NPC 档案追加顺序；不是全世界的因果顺序。事件可按追加顺序、发生时间或获知时间排序；未知时间不能参与对应时间排序或范围过滤。
- 关系流仍是权限边界；参与者匹配不会扩大可见范围。共享流须显式包含。NPC、关系和 as_of 上界检查同样作用于计数、游标、锚点及原文读取。
- 地点和参与者只接受调用方已知信息，不由模型猜测。旧档案一次性增量升级：保留已有 kind/speaker，其他缺失信息保持未知；旧时间仍参与已有 source.timestamp 可见性上界，不伪造旧获知/发生时间。

## 接口

轻量标准库契约位于 memory/events.py；SQL 执行位于档案查询组件，由 MemoryStore 门面公开。

- `EventScope(player_id, include_shared, as_of)`：as_of 必填且有限，默认关系范围仅共享流。
- `EventQuery`：组合事件类型、证据性质、发言者、行为者、目标、全部指定参与者、地点、会话、全文词项、发生/获知时间范围、某原文事件之前/之后的追加顺序，选择排序和升降序。字段不是自然语言问题分类。
- `query_events(scope, query, limit, cursor)`：默认 32 条，上限 128，返回轻量事件记录及下一页游标；不返回全量原文，不创建向量、不强化候选。
- `count_events(scope, query)`：相同筛选的 SQL 精确计数，不把所有事件读入 Python。计数成本随匹配范围增长，不承诺常数耗时。
- `read_event_source(source_id, scope)`：校验同一可见范围后按 ID 返回完整原文；原文很长时调用方仍须控制最终模型上下文。
- 游标绑定档案身份、范围和查询，使用排序键与 sequence 做 keyset 翻页，第一页冻结追加水位；后续新入库、包括回填旧时间的数据不插入本次翻页。无隐式全库导出。
- before_event/after_event 是组合锚点，严格比较追加顺序，可与时间范围并用；不可见或不存在的锚点统一报错。不会猜测“上次争吵”“第几次见面”的事件边界。

例如：先以类型/地点/文本定位赠礼事件，再在其之前查发言事件，倒序取一条，最后按原文 ID 读取。first/last 由排序加 limit=1 表达，次数由 count 表达，不新增专用接口。

## NPC 接入

observe 新增可选事件上下文；调用方可显式提交地点、参与者和发生时间。已有观察入口不猜测自然语言中的人物/地点。直接对话和动作感知可确定双方、发言者、目标、当下发生时间及获知时间，自动提供这些元数据；普通传闻保留 report，发生时间未知。原有参数、去重、补处理及 remember 开关保持兼容。

本轮不改 VisualEvent 序列化及 World 社交窄端口；世界空间/物理结果的结构化回流另行设计。独立 NPC API 可显式提供上下文，世界现有入口通过 NPC 默认路径保留可确定的双方信息。

## 迁移、成本与验收

事件表和参与者索引放在现有 archive.db，升级有持久完成标记、可重启，不新增第三个库；检查点/备份随 SQLite 整库复制。无全量原文 Python 扫描、无全库嵌入；全文过滤复用现有 FTS 片段索引，按 source 去重。

验收覆盖组合筛选、词项与重复片段、精确计数、时间与追加顺序区别、稳定分页、NPC/关系/未来隔离、不可见锚点、旧档案升级/重启、事务回滚、待补处理事件、备份恢复及 NPC 入口。运行离线全集及独立 wheel 安装检查；不运行真实模型，也不把功能测试视作十万轮延迟或任意语义召回验证。

存储阶段实现：memory/events.py 为轻量契约，event_repository.py 负责事件索引与查询，ArchiveRepository 同事务写入，MemoryStore 提供公开入口。事件类型、参与者、时间、锚点、全文词项可自由组合；按时间排序排除对应时间未知的事件，count 与同一查询结果集一致。现有档案检查点格式无需升级。

存储阶段离线验证：114 项通过（事件专项、原文档案、依赖边界和两库检查点），包含独立 NPC 查询隔离。NPC 接入阶段 38 项专项测试通过。无待确认设计冲突。

调用方式（已知事件类型及地点由业务记录方提供，不从问题推断写入）：

```python
from game_agent.memory import EventQuery, EventScope

scope = EventScope(player_id="P", as_of=world_time)
gifts = store.query_events(scope, EventQuery(event_types=("gift",), location="码头"), limit=1)
if gifts.events:
    previous = store.query_events(scope, EventQuery(
        evidence_kinds=("utterance",), before_event=gifts.events[0].source_id,
        speaker="P", descending=True), limit=1)
    if previous.events:
        original = store.read_event_source(previous.events[0].source_id, scope)
```

这里“之前”明确指追加顺序；若业务要按实际发生时间查，使用 occurred_before 和 order_by="occurred_at"。同一时间的严格先后只能依赖业务已有顺序，不能从时间戳恢复未记录的因果关系。

收尾查询计划检查发现：默认单关系、追加顺序分页使用既有关系/时间索引后仍需临时排序。已补充关系/sequence 索引，复验计划使用 source_stream_sequence 且不再出现临时排序；此索引仅改变访问路径。include_shared、多种条件组合和精确计数仍可能扫描或排序，不承诺所有查询具有相同成本。

最终验收（2026-10-25）：事件/NPC 专项 28 项通过；Python 离线全集 522 项通过、6 项真实端点测试跳过（24.71 秒）。新增轻量 events 模块导入边界检查通过。离线 wheel 内容逐文件匹配当前源码，仓库外独立安装、禁网正式导入、记忆隔离及两库检查点往返通过。未修改前端，不重复运行前端检查；未运行真实模型、自然语言规划效果或十万轮负载测试。

本轮未接入自然语言规划器；现有对话历史路由仍调用既有检索接口。新查询接口为上层规划提供可执行操作，显式的地点/业务事件类型需由记录调用方传入；世界位置与物理结果不会自动转换为这些字段。
