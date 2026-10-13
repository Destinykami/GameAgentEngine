# 代码审查记录：记忆 / 反思 / 规划

> 审查范围: memory.py / reflection.py / planning.py 及其上下游
> (npc.py, world.py, llm_real.py, reacting.py, dialogue.py, tests)。
> 严重度: H = 逻辑缺陷, M = 设计缺口/健壮性, L = 卫生/文档漂移。
> 状态: 待修 / 已修 (commit)。逐点修复, 每点一个 commit。

## 反思 (reflection.py)

| ID | 严重度 | 问题 | 位置 | 修法 | 状态 |
|---|---|---|---|---|---|
| H1 | H | `check_conflicts` 置信度衰减不幂等: `_conflict_cache` 只缓存 LLM 判定的矛盾强度, 不缓存"已处置", 每次 `speak()` 触发都对新读到的 confidence 再 ×0.5 (实测 0.8→0.4→0.2), 对话越多塌得越快 | reflection.py:109-142 | 缓存值改记 (severity, 已处置), 或持久化已衰减/已失效的 (反思id, 观察id) 对; 每个冲突对只更新一次 | 已修: 方案 A —— 新增 base_confidence 列 (旧库 PRAGMA+ALTER 迁移), 衰减改为幂等目标水位 `base * 0.5^(不同冲突观察条数)`, 先数后设 + 守卫拦重复写; 重跑不漂移, 新证据恰好多折半一次 |
| H2 | H | confidence 无下游消费者: 检索评分 (memory.py:208-215)、judge_trust 输入 (reacting.py:64)、对话 prompt (llm_real.py:122-123) 全都不用它, 冲突衰减烧钱且零行为效果, 博客 2.2.5 "防不可靠推断被放大" 的动机未兑现 | memory.py:208-215, reacting.py:64, llm_real.py:122-123 | 把 confidence 接进检索评分 (如反思的 relevance 乘 confidence 因子) 和/或 judge_trust 输入; 或降级为纯展示字段并砍掉衰减分支 | 已修: 三处接线 —— retrieve() 评分乘 confidence (与 H1 折半一一对应, 削弱信念排名下降)、judge_trust 改 (类型,内容,置信度) 三元组 + prompt 嘱咐少加权、对话 prompt 对被削弱的反思标注置信度 (观察恒 1.0 不注水) |
| M1 | M | 关系反思兜底问题硬编码 "Klaus 和 {player_id} 的关系如何?", 非 Klaus 的 NPC 兜底时问出外来名字; 引擎不知道 NPC 是谁, 需传入 | reflection.py:87 | 反思方法接收 npc 名 (或引擎持有), 兜底问题用自己的名字 | 已修: ReflectionEngine 构造注入 npc_name (NPC 传 self.name, 默认 "" 向后兼容), 兜底用真名、无名退中性 "NPC"; 同法过滤空白问题 ([""] 不再绕过判空) |
| M2 | M | `check_conflicts` 首次跑长关系是 O(反思×更晚观察) 次 LLM 调用 (10×50=500), 缓存不跨进程; 成本尖峰 | reflection.py:122-141 | 限定只查最近 K 条观察, 或跳过 confidence 已低于阈值的反思 | 待修 |
| L1 | L | `_save` 反思去重每次嵌入该玩家全部已有反思, O(n) 随关系流增长 | reflection.py:149-155 | 缓存反思向量, 或只比较近期反思 | 待修 |
| L9 | L | `reflect_self` 空白问题缺口: 与 M1 同族但 M1 只修了关系反思路径 —— 自我反思拿到 `[""]` 会把空查询流进证据检索 (零向量) 与洞察生成, 无兜底属有意设计 (低价值路径允许静默跳过), 只需补空白过滤 | reflection.py:59-62 | 同 M1 的 `q.strip()` 过滤, 不动无兜底的不对称设计 | 待修 |

## 规划 (planning.py + 集成点)

| ID | 严重度 | 问题 | 位置 | 修法 | 状态 |
|---|---|---|---|---|---|
| H3 | H | 计划产物没传给反应层: `generate_daily_plan` 生成真实计划块后只设 `_current_plan = "日计划已生成"`, `react()`→`score_event` 拿这句空话判 v_goal/c_interrupt, 效用函数目标分量被废 | npc.py:193, npc.py:164, llm_real.py:230 | `_current_plan` 设为当天真实时间块 (或按当前时刻取进行中的块) | 已修: `make_daily_plan`/`replan_from_now` 返回计划块, NPC 存 `_plan_blocks`, `react` 按 `now%24` 取进行中的块; 显式参数 > 当前块 > 重规划中断覆盖 |
| H4 | H | `replan_from_now` 名不副实: 调 `generate_plan(..., "", "replan")` 生成全天计划 (含"07-09 起床"块), 原样打 `[重规划]` 前缀、timestamp=now 入库, 不锚定当前时刻; 旧计划记忆不失效, 新旧两套计划同流共存可被检索 | planning.py:46-58 | prompt 给当前时刻、只生成 now 之后的块并 clamp; 重规划时失效旧 plan 记忆 | 已修: context 告知中断时刻 (LLM 尽力) + 规则层锚点 clamp (整点取整, 过去块丢弃/跨锚块抬起点); 重规划前全部有效 plan 记忆失效 (先收集后存新块) |
| M3 | M | 计划输出零校验: `int(item.get("start", 8))` 遇 "07:00"/"早上" 直接 ValueError 打崩 `World.step`; 重叠/乱序/超 24 的块原样入库; 空计划仍宣称"日计划已生成" | llm_real.py:200-207, llm_real.py:217-224, planning.py:29-43 | 解析时 clamp/丢弃非法块, 全败返回空并让上层跳过 | 已修: `_parse_hour`+`_parse_blocks` 共用助手 (类型容错/"07:00"救援/缺键丢弃/0<=s<e<=24 范围校验, 子任务约束在父块内); 全坏返回 [], 上层 (H3 后) 按诚实空计划处理 |
| M4 | M | plan 记忆只降权不失效: 每天 5-8 块+子任务入库, 衰减到 1.5 触底后永留库里, 30 天模拟堆几百条过期计划污染小存储检索 | memory.py:49-53, planning.py:61-66 | 新一天计划生成时 invalidate 旧 plan, 或 GC 触底的旧计划 | 已修: make_daily_plan 存新块前收集全部有效 plan id, 存完再失效 (同 H4 模式); 空计划也照旧失效 —— 计划是前瞻性的, 跨日后即垃圾, 不适用观察性记忆的"降权不删" |
| M5 | M | 世界模拟从不触发 replan: `step`/`step_autonomous` 只早晨生成日计划, agent 被攻击/状态突变后不重规划, "反应后重规划"只存在于 game_loop.py 手动脚本, 计划在整个 sim 里静态 | world.py:441-470, world.py:336-379 | execute_action 造成状态突变后调 npc.replan; 或文档降级承诺 | 已修: INTERRUPT_ACTIONS (attack/counterattack/flee/help/hide) 执行后行动者 replan (继承 H4 锚定+旧计划失效), 挨打未死的受害者也 replan, "想 XX"未发生结果不触发; 日计划循环跳过死者 (死 NPC 不再每天烧 LLM 规划, 生命止于死亡) |
| L2 | L | `previous_day=f"第{day}天"` 是 0-based 天数标签 (day=1 是第二天却叫"第1天") 而非前一天活动叙事, prompt 语义落空; 计划记忆就在库里可直接取 | world.py:458, world.py:350 | 取最近一天的 plan 记忆做 previous_day, 标签改为真实日期 | 待修 |
| L3 | L | 分解回声防护是精确字符串相等, LLM 换措辞即漏防 (1 小时块主情况已由 cb7ffc5 处理) | planning.py:40-41 | 可留作双保险, 或改语义比较 | 待修 |

## 记忆 (memory.py)

| ID | 严重度 | 问题 | 位置 | 修法 | 状态 |
|---|---|---|---|---|---|
| M6 | M | `merge_observation(mem_id, now, extra_importance)` 的 extra_importance 是死参数: 函数体硬编码 +1.0, npc.observe 传入的 LLM 重要性分被丢弃 (仅用于反思门控累积); 测试恰好传 1.0 掩盖 | memory.py:303-318, npc.py:98-104 | 真的用它 (封顶 10) 或删掉参数 | 已修: 删掉死参数, 语义显式固定为固定 +1 重复强化 (封顶 10) —— 事件重要性首次入库已计入, 重复合并再加全量是双重计分; docstring 写明理由, npc.observe 不再传 importance |
| M7 | M | 检索副作用把"当候选"等同于"被回忆": retrieve() 对 top_k 每条都 _mark_accessed 刷新遗忘锚点, 反思证据检索 (10×3 问) 静默给观察续命; 世界层每步 perceive→observe→去重合并, 玩家逗留期间 last_accessed 每步刷新、感知记忆永不衰减; 叠加 min_score=0.0 + 按候选集 min-max 归一化 (单条候选必得 3.0, 小存储必返回满 top_k 含无关记忆) | memory.py:222-223, memory.py:362-364, memory.py:202-208 | 明确"进 top_k 即视为回忆"写入文档, 或只在对话实际引用时刷新; 加相关性下限 | 已修: ①retrieve 加 mark_accessed 开关 —— 反思两处证据检索传 False (候选≠回忆, 被引用的观察另有证据保护兜底), 对话保持 True 并文档化"进 top_k 即视为回忆"; ②加 min_relevance 下限 (默认 0 向后兼容), dialogue 传 RELEVANCE_FLOOR=0.1 挡零重叠灌水。世界层 perceive→merge 每步刷新属 by-design (重复=强化, merge 文档已写明), 不改 |
| L4 | L | `_vec_cache` 无上限且不跨进程, RealEmbedder 下恢复大世界后首波检索 O(n) 次网络嵌入 (HashEmbedder 无感) | memory.py:79-80, memory.py:140-146 | 注释写明冷启动行为; 量大后再议 | 待修 |
| L5 | L | `find_similar_observation` 只看同玩家最近 50 条, 窗口外的重放会重复入库 | memory.py:281-301 | 可接受, 或扩大窗口 | 待修 |
| L6 | L | retrieve 是读操作却写库 (UPDATE last_accessed), 调试/审查调用会改变衰减时钟; 与 M7 同源 | memory.py:237-242 | 随 M7 一并处理 | 待修 |

## 周边 (与三模块相关的其他文件)

| ID | 严重度 | 问题 | 位置 | 修法 | 状态 |
|---|---|---|---|---|---|
| M8 | M | 反思洞察证据 id 无校验: prompt 枚举真实记忆 id (如 101,103), 模型可能回 [1,3], ev_ids 不校验归属就入库, 证据链断成幻影 id, decay 保护集保护不存在的 id, inspect_npc 展示断链 | llm_real.py:176-183 | 过滤 ev_ids ∩ 传入 id 集, 空则回退全部证据 | 已修: `reflection_insights` 引用编号过滤到传入 id 集, 全幻影/空引用回退全引传入证据 (宁宽勿断链), 集成测试断言入库反思证据 id 全部真实存在 |
| M9 | M | `World.load` 丢失实体状态: entity 表只存 name/kind/location/x/y, health/goal/attack/role/history/reasons 全丢, 跨进程恢复后将军血条回 100、旅行者攻与理由清零, 自治弧线作废 (NPC 记忆流本身持久化是对的) | world.py:484-542 | 补字段进 entity 表, 或文档明确"只恢复位置与时钟" | 已修: entity 表补 8 列 (health/attack/defense/goal/dead/role/history/reasons), save 写全字段, load 按全字段重建 Entity; 旧库 PRAGMA+ALTER 迁移按 Entity 默认值兜底 (旧库本就没存过这些状态)。死者不复活、role 特殊判定与说服理由跨进程保留 |
| L7 | L | `world_event` 不检查 NPC 死亡, dead NPC 也会感知世界事件 (step 的 perceive/reflection 都检查了) | world.py:435-436 | 加 dead 检查 | 待修 |
| L8 | L | 文档漂移: llm.py 头注"十类推理", OVERVIEW 说 9, 实际抽象方法 11 个 | llm.py:3, OVERVIEW.md:40-64 | 统一为 11 (或按功能分组重述) | 待修 |

## 测试缺口 (现有 40 个测试都没锁住)

| ID | 锁定目标 | 对应修复 | 状态 |
|---|---|---|---|
| T1 | 置信度衰减幂等: 同一 (ref, obs) 对检查两次, confidence 只降一次 | H1 | 已修: tests/test_confidence.py (幂等重跑/新证据再折半/强矛盾失效不衰减/检索折减精确减半/信任三元组/对话标注) |
| T2 | replan 锚定: 重规划块时间 ≥ now, 旧计划被失效 | H4 | 已修: tests/test_replan.py (4 用例: 裁过去块/旧计划失效/深夜无块/整点不误伤) |
| T3 | react 拿到的 plan 含真实活动 (非"日计划已生成") | H3 | 已修: tests/test_plan_react.py (4 用例: 当前块/无块兜底/重规划中断/显式参数优先) |
| T4 | merge_observation 对 importance 的实际行为 (当前恰好传 1.0 掩盖死参数) | M6 | 已修: test_forgetting 新增重复观察走生产路径 (observe→去重合并) 断言 +1 非双重计分 + last_accessed 刷新, 及 30 次 merge 收敛到上限 10 |

## 修复顺序建议

1. H1 + H2 (反思置信度: 幂等 + 接入下游, 博客 2.2.5 的设计意图)
2. H3, H4 (规划→反应链路)
3. M3, M8 (LLM 输出校验)
4. M6, M7 (记忆语义)
5. 其余 M/L 逐项
