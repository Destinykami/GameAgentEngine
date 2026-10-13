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
| M2 | M | `check_conflicts` 首次跑长关系是 O(反思×更晚观察) 次 LLM 调用 (10×50=500), 缓存不跨进程; 成本尖峰 | reflection.py:122-141 | 限定只查最近 K 条观察, 或跳过 confidence 已低于阈值的反思 | 已修: 两端各砍一刀 —— 每反思只查最近 CONFLICT_RECENT_OBS=10 条更晚观察 (按时间戳显式排序取窗口), 首跑/重启成本 O(反思×观察)→O(反思×K); 置信度 < CONFLICT_DECAY_FLOOR=0.1 的反思整条跳过 (功能上已死), 活跃反思随衰减递减。K 窗口同时给衰减自然地板 (decay_count≤K, 信念最低 base×0.5^K 不被磨零)。窗口外旧矛盾不回查是有意取舍 (它该在新证据期被处理)。不持久化缓存 (K 封顶已压住尖峰) |
| L1 | L | `_save` 反思去重每次嵌入该玩家全部已有反思, O(n) 随关系流增长 | reflection.py:149-155 | 缓存反思向量, 或只比较近期反思 | 已修: 去重改走 store.vector() 取已有反思的缓存向量 (add 时已嵌入), 不再整批重嵌入 —— RealEmbedder (无自缓存) 下每存一条反思的 O(n) 网络嵌入降为 O(1), 只嵌入新洞察 |
| L9 | L | `reflect_self` 空白问题缺口: 与 M1 同族但 M1 只修了关系反思路径 —— 自我反思拿到 `[""]` 会把空查询流进证据检索 (零向量) 与洞察生成, 无兜底属有意设计 (低价值路径允许静默跳过), 只需补空白过滤 | reflection.py:59-62 | 同 M1 的 `q.strip()` 过滤, 不动无兜底的不对称设计 | 已修: reflect_self 补同款 `isinstance+strip` 过滤, 空白问题静默跳过, 空查询不再流入证据检索; 无兜底的不对称设计原样保留 |

## 规划 (planning.py + 集成点)

| ID | 严重度 | 问题 | 位置 | 修法 | 状态 |
|---|---|---|---|---|---|
| H3 | H | 计划产物没传给反应层: `generate_daily_plan` 生成真实计划块后只设 `_current_plan = "日计划已生成"`, `react()`→`score_event` 拿这句空话判 v_goal/c_interrupt, 效用函数目标分量被废 | npc.py:193, npc.py:164, llm_real.py:230 | `_current_plan` 设为当天真实时间块 (或按当前时刻取进行中的块) | 已修: `make_daily_plan`/`replan_from_now` 返回计划块, NPC 存 `_plan_blocks`, `react` 按 `now%24` 取进行中的块; 显式参数 > 当前块 > 重规划中断覆盖 |
| H4 | H | `replan_from_now` 名不副实: 调 `generate_plan(..., "", "replan")` 生成全天计划 (含"07-09 起床"块), 原样打 `[重规划]` 前缀、timestamp=now 入库, 不锚定当前时刻; 旧计划记忆不失效, 新旧两套计划同流共存可被检索 | planning.py:46-58 | prompt 给当前时刻、只生成 now 之后的块并 clamp; 重规划时失效旧 plan 记忆 | 已修: context 告知中断时刻 (LLM 尽力) + 规则层锚点 clamp (整点取整, 过去块丢弃/跨锚块抬起点); 重规划前全部有效 plan 记忆失效 (先收集后存新块) |
| M3 | M | 计划输出零校验: `int(item.get("start", 8))` 遇 "07:00"/"早上" 直接 ValueError 打崩 `World.step`; 重叠/乱序/超 24 的块原样入库; 空计划仍宣称"日计划已生成" | llm_real.py:200-207, llm_real.py:217-224, planning.py:29-43 | 解析时 clamp/丢弃非法块, 全败返回空并让上层跳过 | 已修: `_parse_hour`+`_parse_blocks` 共用助手 (类型容错/"07:00"救援/缺键丢弃/0<=s<e<=24 范围校验, 子任务约束在父块内); 全坏返回 [], 上层 (H3 后) 按诚实空计划处理 |
| M4 | M | plan 记忆只降权不失效: 每天 5-8 块+子任务入库, 衰减到 1.5 触底后永留库里, 30 天模拟堆几百条过期计划污染小存储检索 | memory.py:49-53, planning.py:61-66 | 新一天计划生成时 invalidate 旧 plan, 或 GC 触底的旧计划 | 已修: make_daily_plan 存新块前收集全部有效 plan id, 存完再失效 (同 H4 模式); 空计划也照旧失效 —— 计划是前瞻性的, 跨日后即垃圾, 不适用观察性记忆的"降权不删" |
| M5 | M | 世界模拟从不触发 replan: `step`/`step_autonomous` 只早晨生成日计划, agent 被攻击/状态突变后不重规划, "反应后重规划"只存在于 game_loop.py 手动脚本, 计划在整个 sim 里静态 | world.py:441-470, world.py:336-379 | execute_action 造成状态突变后调 npc.replan; 或文档降级承诺 | 已修: INTERRUPT_ACTIONS (attack/counterattack/flee/help/hide) 执行后行动者 replan (继承 H4 锚定+旧计划失效), 挨打未死的受害者也 replan, "想 XX"未发生结果不触发; 日计划循环跳过死者 (死 NPC 不再每天烧 LLM 规划, 生命止于死亡) |
| L2 | L | `previous_day=f"第{day}天"` 是 0-based 天数标签 (day=1 是第二天却叫"第1天") 而非前一天活动叙事, prompt 语义落空; 计划记忆就在库里可直接取 | world.py:458, world.py:350 | 取最近一天的 plan 记忆做 previous_day, 标签改为真实日期 | 已修: generate_daily_plan 取库里昨日计划记忆 (M4 失效前仍 valid) 拼成"前一天活动: …"叙事, 首日/无计划时退回调用方标签, 计划从此基于真实昨日活动 |
| L3 | L | 分解回声防护是精确字符串相等, LLM 换措辞即漏防 (1 小时块主情况已由 cb7ffc5 处理) | planning.py:40-41 | 可留作双保险, 或改语义比较 | 已修 (文档): 注释写明这是双保险 —— 主防护是跳过 1 小时块, 精确相等只拦原样回声的漏网, 换措辞近重复可接受 (轻微冗余非正确性问题), 不为 cosmetic 去重引入语义比较成本 |

## 记忆 (memory.py)

| ID | 严重度 | 问题 | 位置 | 修法 | 状态 |
|---|---|---|---|---|---|
| M6 | M | `merge_observation(mem_id, now, extra_importance)` 的 extra_importance 是死参数: 函数体硬编码 +1.0, npc.observe 传入的 LLM 重要性分被丢弃 (仅用于反思门控累积); 测试恰好传 1.0 掩盖 | memory.py:303-318, npc.py:98-104 | 真的用它 (封顶 10) 或删掉参数 | 已修: 删掉死参数, 语义显式固定为固定 +1 重复强化 (封顶 10) —— 事件重要性首次入库已计入, 重复合并再加全量是双重计分; docstring 写明理由, npc.observe 不再传 importance |
| M7 | M | 检索副作用把"当候选"等同于"被回忆": retrieve() 对 top_k 每条都 _mark_accessed 刷新遗忘锚点, 反思证据检索 (10×3 问) 静默给观察续命; 世界层每步 perceive→observe→去重合并, 玩家逗留期间 last_accessed 每步刷新、感知记忆永不衰减; 叠加 min_score=0.0 + 按候选集 min-max 归一化 (单条候选必得 3.0, 小存储必返回满 top_k 含无关记忆) | memory.py:222-223, memory.py:362-364, memory.py:202-208 | 明确"进 top_k 即视为回忆"写入文档, 或只在对话实际引用时刷新; 加相关性下限 | 已修: ①retrieve 加 mark_accessed 开关 —— 反思两处证据检索传 False (候选≠回忆, 被引用的观察另有证据保护兜底), 对话保持 True 并文档化"进 top_k 即视为回忆"; ②加 min_relevance 下限 (默认 0 向后兼容), dialogue 传 RELEVANCE_FLOOR=0.1 挡零重叠灌水。世界层 perceive→merge 每步刷新属 by-design (重复=强化, merge 文档已写明), 不改 |
| L4 | L | `_vec_cache` 无上限且不跨进程, RealEmbedder 下恢复大世界后首波检索 O(n) 次网络嵌入 (HashEmbedder 无感) | memory.py:79-80, memory.py:140-146 | 注释写明冷启动行为; 量大后再议 | 已修 (文档): _vec_cache 初始化处注释写明冷启动行为与"向量不入库"的取舍 (持久化要存几百维浮点/条且与嵌入模型版本耦合), 量大后再议持久化/LRU |
| L5 | L | `find_similar_observation` 只看同玩家最近 50 条, 窗口外的重放会重复入库 | memory.py:281-301 | 可接受, 或扩大窗口 | 已修 (文档): 注释写明窗口取舍 —— 窗口外重放是低频边缘的轻微灌水, 不值得用高频 observe 路径的 O(窗口) 余弦成本去兜, 保持 50 |
| L6 | L | retrieve 是读操作却写库 (UPDATE last_accessed), 调试/审查调用会改变衰减时钟; 与 M7 同源 | memory.py:237-242 | 随 M7 一并处理 | 已修 (M7 顺手解决): M7 加的 `mark_accessed` 开关就是"读而不改衰减时钟"的入口, 调试/审查调用传 mark_accessed=False 即可, 无需再动代码 |

## 周边 (与三模块相关的其他文件)

| ID | 严重度 | 问题 | 位置 | 修法 | 状态 |
|---|---|---|---|---|---|
| M8 | M | 反思洞察证据 id 无校验: prompt 枚举真实记忆 id (如 101,103), 模型可能回 [1,3], ev_ids 不校验归属就入库, 证据链断成幻影 id, decay 保护集保护不存在的 id, inspect_npc 展示断链 | llm_real.py:176-183 | 过滤 ev_ids ∩ 传入 id 集, 空则回退全部证据 | 已修: `reflection_insights` 引用编号过滤到传入 id 集, 全幻影/空引用回退全引传入证据 (宁宽勿断链), 集成测试断言入库反思证据 id 全部真实存在 |
| M9 | M | `World.load` 丢失实体状态: entity 表只存 name/kind/location/x/y, health/goal/attack/role/history/reasons 全丢, 跨进程恢复后将军血条回 100、旅行者攻与理由清零, 自治弧线作废 (NPC 记忆流本身持久化是对的) | world.py:484-542 | 补字段进 entity 表, 或文档明确"只恢复位置与时钟" | 已修: entity 表补 8 列 (health/attack/defense/goal/dead/role/history/reasons), save 写全字段, load 按全字段重建 Entity; 旧库 PRAGMA+ALTER 迁移按 Entity 默认值兜底 (旧库本就没存过这些状态)。死者不复活、role 特殊判定与说服理由跨进程保留 |
| L7 | L | `world_event` 不检查 NPC 死亡, dead NPC 也会感知世界事件 (step 的 perceive/reflection 都检查了) | world.py:435-436 | 加 dead 检查 | 已修: world_event 遍历加 `if entities[name].dead: continue`, 死者不感知世界事件, 与 step/日计划循环的死亡检查对齐 |
| L8 | L | 文档漂移: llm.py 头注"十类推理", OVERVIEW 说 9, 实际抽象方法 11 个 | llm.py:3, OVERVIEW.md:40-64 | 统一为 11 (或按功能分组重述) | 已修: llm.py 头注"十类"→"十一类", OVERVIEW 标题/计数 9→11 并补 perceive_action/decide_action 两行, 与实际抽象方法数对齐 |

## 测试缺口 (现有 40 个测试都没锁住)

| ID | 锁定目标 | 对应修复 | 状态 |
|---|---|---|---|
| T1 | 置信度衰减幂等: 同一 (ref, obs) 对检查两次, confidence 只降一次 | H1 | 已修: tests/test_confidence.py (幂等重跑/新证据再折半/强矛盾失效不衰减/检索折减精确减半/信任三元组/对话标注) |
| T2 | replan 锚定: 重规划块时间 ≥ now, 旧计划被失效 | H4 | 已修: tests/test_replan.py (4 用例: 裁过去块/旧计划失效/深夜无块/整点不误伤) |
| T3 | react 拿到的 plan 含真实活动 (非"日计划已生成") | H3 | 已修: tests/test_plan_react.py (4 用例: 当前块/无块兜底/重规划中断/显式参数优先) |
| T4 | merge_observation 对 importance 的实际行为 (当前恰好传 1.0 掩盖死参数) | M6 | 已修: test_forgetting 新增重复观察走生产路径 (observe→去重合并) 断言 +1 非双重计分 + last_accessed 刷新, 及 30 次 merge 收敛到上限 10 |

## 外部审查交叉核对 (第二轮)

> 来源: 另一份独立审查, 读了三模块源码 + 离线实验 (stub LLM + 真实 gte-Qwen2
> 向量端点) + 分析真实跑出的 `data/sim/*.db`、`data/auto_sim/*.db`。
> 编号 E1–E16 为**外部编号**, 与本文件 H/M/L/T 编号是两套体系, 勿混。
> 状态为本轮逐条复核后的现状: 仍存在 / 已修 (指向本文件对应修复) / 部分修 / 基本不成立。
> 复核方法: 直接读当前源码 + 对 M1 复现实验 (单次衰减 vs 6h 高频清扫)。

| ID | 外部级别 | 问题 | 位置 | 外部建议 | 现状 (本轮复核) |
|---|---|---|---|---|---|
| E1 | 高 | 遗忘衰减复合叠加: `new_imp = m.importance * 0.5**(age/hl)`, importance 是已降过的当前值、age 用固定锚点算全部年龄, 每清扫一次再乘满年龄因子 → 随清扫次数 n² 加速, 半衰期语义失效 | memory.py (decay_and_forget) | 存 base_importance 或 decayed_at, 改对原始值/增量衰减 | **已修** (同 H1 幂等水位): 新增 base_importance 列 (旧库 PRAGMA+ALTER 迁移, 逐行 UPDATE 基线=当前 importance), 衰减改对基线幂等重算 `base_importance * 0.5**(age/hl)`, 只降不升守卫保留; merge 提升 importance 时同步抬高基线 (增益不被抹掉), 回忆刷新 last_accessed 仍抗遗忘 (锚点后移)。实测: 单次 48h=4.0 且每 6h 清扫到 48h 也=4.0 (旧实现触底 1.5), 重扫不漂移。回归: test_forgetting 新增 3 用例 (幂等非复合/重扫不漂移/merge 抬基线) |
| E2 | 中 | `player_id=None` 双重语义: `all_valid(None)`="返回所有玩家", 而文档语义是"世界/自我共享流 (player_id IS NULL)", 无 API 能只取 NULL 流 | memory.py (all_valid/retrieve) | 拆分"不过滤"与"共享流"两种语义 | **已修**: all_valid/retrieve 加 `shared` 参数 —— `shared=True` 选 `player_id IS NULL` (共享流), `player_id=None` 仍是"不过滤" (衰减/计划/近期上下文照旧); relationship_trust(None) 直接返回中性 0.0 (世界事件无关系, 不再合判全玩家记忆)。下游 E8 随之修复 |
| E3 | 中 | `merge_observation` 的 extra_importance 死参数被忽略 | memory.py, npc.py | 真用或删参数 | **已修** (=本文件 M6, 删死参数, merge 固定 +1) |
| E4 | 低 | 检索无绝对相关性下限, min_score 无调用方传值, top-1 永远 ≈3.0, "答不上来"永不触发 | memory.py:194-286 | 用归一化前原始 cosine 做绝对门槛 | **已修** (=本文件 M7, 加 min_relevance 原始余弦下限, dialogue 传 0.1) |
| E5 | 低 | `find_similar_observation` 依赖未排序 SELECT (`all_valid(...)[-recent_n:]` 靠 rowid 恰好有序) | memory.py (all_valid) | 加 `ORDER BY id` | **已修**: all_valid 加显式 `ORDER BY id` (id 自增=插入序=时间序), 多处 `[-n:]` 取"最近 n 条" (去重窗口/反思近期观察/世界记忆上下文) 不再靠 SQLite 恰好按 rowid 返回的隐性依赖。回归: test_shared_stream 新增按 id 有序/[-2:] 取最近/失效后仍有序 |
| E6 | 高 | 0.95 去重阈值在真实数据几乎不生效: 同义复述稳定落 0.85–0.94, ≥0.95 仅 0.1%, 9 条观察产出 48 条反思 | reflection.py (DEDUP_THRESHOLD) | 降阈值或改去重策略 | **已修**: DEDUP_THRESHOLD 0.95→0.92, 抓得住明显近重复 (那几条"旅行者藏眼"变体), 0.90~0.92 重叠区是已知取舍 (独立洞察多 ≤0.90, 宁可少误并)。OBS_DEDUP_THRESHOLD 本就 0.92, 两层对齐。回归: 预设向量卡阈值两侧 (0.93 去重 / 0.90 保留), 锁边界行为 |
| E7 | 高 | 合并观察仍累加 importance → 同一事实反复触发反思 (1 条观察零新信息, 6 步产出 6 条反思) | npc.py (observe merge 分支) | merge 分支不累加 importance (或只 +0.2) | **已修**: merge 分支不再累积到 `_importance_accum` —— 合并的重复是零新信息, 反思该由新信息驱动, 不是旧信息的反复强化; 强化已由 merge 的 +1 importance 承担 (显著度信号, 检索排名上升), 不是反思信号。新观察照常累积。实测: 同一条观察重放 6 次累积=5.0 (旧实现 30.0), 换新观察 +5 照常。回归: test_forgetting 新增"merge 不累积反思触发器"用例 |
| E8 | 高 | 自我反思吃掉关系观察: `reflect_self` 用 `all_valid(None, observation)`=全玩家观察, 产出 player_id=None 反思 (对所有玩家可见), 违反"自我/面解耦" | reflection.py (reflect_self) | 拆分共享流语义 (随 E2) | **已修** (随 E2): reflect_self 的观察源与证据检索都改 `shared=True` (只取 NULL 流), 自我反思只基于世界/自我观察, 不再吞某玩家的关系观察 (那是关系反思的料)。回归: tests/test_shared_stream (证据指向共享观察 id, 非关系观察) |
| E9 | 中 | 冲突衰减重复叠加 (同一对每次 check_conflicts 再砍半) | reflection.py | 幂等处置 | **已修** (=本文件 H1, 幂等目标水位) |
| E10 | 中 | 关系反思 fallback 硬编码 "Klaus" | reflection.py | 注入 NPC 名 | **已修** (=本文件 M1, `self._npc_name or "NPC"`) |
| E11 | 中 | 反思去重成本 O(已有反思数) 次重复编码, 绕过 _vec_cache | reflection.py (_save) | 缓存向量 | **已修** (=本文件 L1, 走 store.vector() 缓存) |
| E12 | 高 | `_current_plan` 存占位符非计划内容, 反应缓存键恒定, 计划层与反应层那根线断了 | npc.py:164-235 | _current_plan 设为真实时间块 | **已修** (=本文件 H3, `_current_activity(now)` 按小时取真实活动块, 缓存键随真实计划变) |
| E13 | 中 | 重规划不淘汰旧计划, plan 记忆无限增殖 (真实库 plan 占 80–95%) | planning.py:61-96 | 新计划时 invalidate 旧 plan + 加 date 字段 | **已修** (=本文件 M4+H4, make_daily_plan 与 replan_from_now 都失效旧计划)。注: 失效是 valid=0 不删除, 库里无效行仍累积 (纯存储债, 不参与检索/反思) |
| E14 | 中 | 重规划不继承世界背景 (make_daily_plan 喂近期观察, replan 只喂中断锚定 context) | planning.py (replan_from_now) | replan 也喂近期观察世界背景 | **已修**: replan_from_now 加 context 参数携带世界背景 (近期观察), npc.replan 取 `all_valid(observation)[-10:]` 传入 (同 generate_daily_plan); 世界背景在前 + 中断锚定指令在后, 被打断后仍在世界背景下重排 (持眼者逢眼狩令仍规划躲避)。回归: test_replan 新增"重规划 context 含世界背景+中断锚定" |
| E15 | 中 | 分解子任务与顶层块重复, 子任务时间不 clamp 到 [start,end] (模型给 03-04 照存) | planning.py:40-58 | clamp 子任务时间 + 去重 | **部分修** (重复主来源已挡: 跳 1 小时块 + 精确相等兜底 = 本文件 L3; 但 LLM 按小时切分父活动仍存多条, 且子任务时间仍无 clamp) |
| E16 | 架构 | 旗舰 world_auto_sim 绕开记忆/反思层: 自治对话/动作只写 Entity.history/reasons, 不进 npc.store, react/speak/reflect_relationship/trust 自治循环一次未调, 劝说弧线靠脚本计数器+reasons | world.py:261-338 (execute_action), 340-406 (step_autonomous) | execute_action 的 talk/attack/help 对目标走 observe/perceive_action, 让 trust/反思参与判定; 或文档明确这条 demo 只用世界层 | **仍存在** (execute_action 的 talk/attack/help 只调 agent.record()/target.record() 写 Entity.history + add_reason() 写 reasons, 从不对目标 observe; 自治循环只调 generate_daily_plan/decide_agent/execute_action/perceive/maybe_reflect_self, 无 react/speak/reflect_relationship/trust。本文件 M5 只加了"被打断就重规划"(计划层), 没接记忆/信任到决策线) |

> 注: 外部 P5 ("计划被打断"观察 importance 写死 5.0 会触发反思) 复核后**基本不成立** ——
> `planning._save_obs` 直接 `store.add`, 绕过 `npc.observe()`, 不进 `_importance_accum`,
> 不会凭固定分触发反思; 仅剩"importance 硬编码 5.0 而非 score_importance"的轻微卫生点。
> 未单列编号。

### 仍存在项的修复顺序建议

1. **E1 复合衰减** (高): 存 base_importance, 幂等衰减 `base * 0.5**(age/hl)`, 同 H1 思路; 加多清扫回归测试
2. **E2 + E8 player_id=None 歧义** (高): 拆"不过滤"与"共享流 (NULL)"语义, reflect_self 只取 NULL 流; 连带 E13 的 relationship_trust(None) 合判
3. **E7 合并观察累加** (高): merge 分支不累加 (或只 +0.2) importance 到反思触发器
4. **E6 去重阈值** (高): 降 DEDUP_THRESHOLD 或改去重策略 (需真实向量复测定阈值)
5. **E5 未排序 SELECT** (低): all_valid 加 ORDER BY id
6. **E14/E15 重规划世界背景 + 子任务 clamp** (中): 补齐
7. **E16 自治世界记忆/信任接线** (架构): 单独讨论方案 (动 execute_action 让目标 NPC 感知, 接入 trust/反思判定)

## 修复顺序建议

1. H1 + H2 (反思置信度: 幂等 + 接入下游, 博客 2.2.5 的设计意图)
2. H3, H4 (规划→反应链路)
3. M3, M8 (LLM 输出校验)
4. M6, M7 (记忆语义)
5. 其余 M/L 逐项
