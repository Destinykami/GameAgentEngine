# EvalPlan — 三实验评测体系实施计划

> **状态：已完成**。三实验脚本、smoke/全量跑批与结果表均已落地，方法学与
> 结果见 [evals/README.md](evals/README.md)；本文件保留为设计记录。

为 persona_agent 补上一套真实 LLM 的评测 harness，回答三个问题：

1. **实验 1（记忆一致性）**：证据约束反思 + LLM 矛盾判别 + 置信度衰减，是否真的降低了过期记忆召回与认知冲突？
2. **实验 2（决策消融）**：人格×关系的效用决策，是否比固定优先级、无关系权重的效用决策更"符合人格与关系设定"？
3. **实验 3（调度效率）**：三级认知调度能否在关键交互决策质量基本不变的前提下，把推理成本压到近似常数、随 NPC 数扩展？

设计总原则（三条铁律，执行时随时对照）：

- **包内改动只做增量**：新构造参数缺省值 = 现系统行为；游戏路径（examples/、demo）不传任何新参数时逐字节不变。
- **依赖方向单向**：`evals/ → persona_agent/`，包永远不 import evals；harness 只通过公开 API 观察，禁止 monkeypatch。
- **两道回归闸门**：每次包内改动提交前，离线测试（tests/，stub LLM 零网络）+ 6 个真实 LLM 探针（probes.py）必须全绿。

---

## 一、包内改动清单（全部增量，缺省=现行为）

| # | 文件 | 改动 | 缺省行为 | 服务的实验 |
|---|---|---|---|---|
| P1 | `persona_agent/reflection.py` | `ReflectionEngine` 加参数 `evidence_types=("observation",)`、`conflict_policy="full"`、`evidence_min_relevance=0.0` | 证据只引用观察、LLM 矛盾判别、不过滤候选——与现状一致 | 1 / 3 |
| P2 | `persona_agent/reflection.py` | `check_conflicts` 改入口分派：`"full"`（现 LLM 路径，原体迁移为 `_check_conflicts_llm`）/ `"heuristic_decay"`（新增：TRUST/DISTRUST 词表方向矛盾，只衰减不失效，幂等目标水位，零 LLM）/ `"off"`（空操作） | `"full"` 即现状 | 1（消融臂） |
| P3 | `persona_agent/npc.py` | `NPC.__init__` 透传 4 个参数给 ReflectionEngine / ReactionDecider（`conflict_policy`、`evidence_types`、`evidence_min_relevance`、`use_relationship`） | 全传缺省值 | 1 / 2 |
| P4 | `persona_agent/reacting.py` | `ReactionDecider` 加 `use_relationship=True`；`False` 时 `trust_mod` 钉死 1.0 | 信任调制不变 | 2（消融臂） |
| P5 | `persona_agent/llm_real.py` | `RealLLM` 加 usage 计数器（calls / prompt_tokens / completion_tokens / total_latency_s / by_method 分桶），`_chat` 唯一记账点（成功失败都计，usage 缺失记 0）；`_chat` / `_chat_json` 加 `_stats_tag` 透传推理类别 | 纯增量字段，不改任何调用行为 | 3（成本指标） |
| P6 | `persona_agent/world.py` | `World` 加 `force_full_tier=False`；`schedule_tiers` 在 True 时全员 full | 距离调度不变 | 3（all-full 基线） |
| P7 | `persona_agent/planning.py` | `PlanningEngine` 加 `daily_plan_count` / `replan_count` 两个计数属性 | 纯增量 | 2（计划打断率） |
| P8 | `persona_agent/world.py` | `World` 加 `decision_tier_gate=False`；`step_autonomous` 决策循环中 idle 档 NPC 走规则等待（零 LLM），玩家 agent 不受门控 | 缺省关，决策循环逐字节不变 | 3（调度决策层落点） |

**P8 的必要性（跑批前发现的设计缺口）**：现 `step_autonomous` 对每个存活 agent 每步都调 `decide_action`，完全不受档位约束——"调度省成本"在决策层没有落点，all-full 与调度臂的每步成本几乎相同（感知本就受视距门控）。P8 把三级调度的本意（视距内无人时远处 NPC 无需 LLM 战略决策）实现为可开关的决策门控，是实验 3 的对照杠杆。

**不需要的东西**（评估过，砍掉）：MeteredLLM 包装类——实验脚本给每个 NPC 传独立 `RealLLM()` 实例即可（RealLLM 无内部状态缓存，独立实例不改变缓存语义），per-NPC 成本天然隔离。

## 二、新增离线测试 `tests/test_eval_flags.py`（stub LLM，零网络）

- P2：`conflict_policy="off"` 后背叛观察 + 反思 → 置信度不变、valid 不变；`"heuristic_decay"` → 信任方向矛盾的反思按 `base*0.5**k` 衰减、**不失效**（valid 恒 1）、重跑幂等不复合。
- P1：`evidence_types=("observation","reflection")` 时反思证据可含反思 id；缺省仍只含观察。
- P4：`use_relationship=False` 时 trust=-1 与 trust=0 的效用相同；True 时不同。
- P5：不可达端点 + `max_retries=0` → 异常抛出但 `stats["calls"]==1`（失败尝试也记账）。
- P6：`force_full_tier=True` 时远处玩家下所有 NPC 档位 full。
- P7：generate_daily_plan / replan 后计数器各 +1。

## 三、`evals/` 目录结构（新建，与 examples/ 平级，全量入库）

```
evals/
  README.md               # 方法学：指标定义、口径决策、跑法、结果表（跑批后回填）
  common.py               # 共用件：NPC 工厂、t1→t5 轨迹构造器、LLM 裁判（YES/NO，temperature=0）、
                          #   指标计算（EGR/Stale Recall/ERR/一致率）、结果落盘（runs.json + metrics.json）
  scenarios.py            # 实验 2 场景定义：3 人格 × 3 信任档 × 6 事件脚本 + 期望响应表（声明式 dict）
  memory_consistency.py   # 实验 1 主脚本（--smoke 1 条轨迹 / 全量 4 臂 × 10 轨迹）
  decision_ablation.py    # 实验 2 主脚本（--smoke 1 切片 / 全量 3 方法 × 54 场景）
  scheduling_efficiency.py# 实验 3 主脚本（--smoke N=2×2 步 / 全量 3 配置 × N 扩展）
```

脚本惯例照抄 examples/：无 `__init__.py`、纯标准库、文件头 docstring 写方法说明 + 跑法 + 预计耗时、`sys.path.insert` 引包。运行产物落 `data/eval/<实验>/<时间戳>/`，被现有 `/data/` 与 `*.db` 忽略规则自动挡在库外。

**依赖方向自查**：`evals/` 只 import `persona_agent`；`persona_agent/`、`examples/`、`tests/` 任何文件不出现 `evals`。

## 四、实验设计（指标的操作化定义，跑前冻结）

### 实验 1：四臂消融

| 臂 | 证据类型 | 冲突策略 | 隔离的机制 |
|---|---|---|---|
| baseline | `("observation","reflection")` | `"off"` | Generative Agents 原始反思 |
| ablation_a | `("observation",)` | `"off"` | 证据约束（级联切断） |
| ablation_b | `("observation","reflection")` | `"heuristic_decay"` | 衰减机制本身（无 LLM 判别） |
| ours | `("observation",)` | `"full"` | 证据约束 + LLM 矛盾判别 + 置信度衰减 |

轨迹（每臂 × 10 条，措辞语义多样化，防去重误并）：t1 玩家帮助（2–3 观察）→ t2 `reflect_relationship`（记录产出的反思 id = **stale 集**）→ t3 玩家背叛（1–2 观察）→ t4 `reflect_relationship`（矛盾处理在此生效）→ t5 再交互：关系相关查询检索 + `speak` 回应。

- **Evidence Grounding Rate**：每条反思的 evidence 链全指向 observation 的比例（读库计算，零裁判）。ours/ablation_a 结构性 100%，baseline/ablation_b 看级联引用比例。
- **Stale Memory Recall Rate**：t5 检索 top-k 中 stale 集条目的占比与平均排名。口径说明：被**失效**的反思（valid=0）进不了检索（`all_valid` 过滤），ours 臂趋 0 是机制使然；有意义信号在 baseline/a（过期但 valid，高召回）vs b（衰减后被 confidence 乘数压排名）。
- **Contradiction Rate**：两级。context 级（确定性）：top-k 同时含 stale 信任断言与背叛观察 = 认知冲突；utterance 级（LLM 裁判 YES/NO）：t5 回复是否自相矛盾。
- 嵌入用 `make_embedder()`（真实 gte-Qwen2）——HashEmbedder 是词面哈希，"过期召回"语义会失真。

### 实验 2：三方法 × 场景矩阵

方法：`fixed_priority`（evals 内实现的关键词固定优先级基线：危险 > 求助 > 社交 > 继续计划——经典规则式基线，与现系统"离开词表"的设计恰好构成对比）/ `no_relationship`（P4 开关）/ `full`（现系统）。

场景：3 人格（social 0.8 / 0.5 / 0.2 为主）× 3 信任档（高信任=3 次帮助 / 中立=1 次寒暄 / 低信任=帮助后背叛）× 6 事件脚本（藏眼求助 / 派对邀请 / 低价值闲聊 / 敌对挑衅 / 委托打铁 / 背叛者再求助），**期望响应表按人格×关系逻辑预先定义**（什么情况下该响应、什么情况下忽略低价值事件才是正确行为——事件响应率不是越高越好，正确性由期望表定义）。

- **Goal Completion Rate**：场景日内日计划存活率——对中断类事件（求助/危险，对应世界层 `INTERRUPT_ACTIONS` 语义）的**错误响应**触发重规划（镜像 `step_autonomous` M5 逻辑），GCR = 1 − 错误中断/场景数。
- **Event Response Rate**：决策 react 与期望表一致率。
- **Relationship Consistency**：确定性——同事件高/低信任对的响应分化率（E2/E5/E6）。
- **Persona Consistency**：确定性——同人格对间响应分化率（目标型婉拒派对、社交型接受；目标型接委托、社交型婉拒）；辅以 LLM 裁判对决策理由文本的软评分（注明未人工校准的保留）。
- **Plan Disruption Rate**：`replan_count / daily_plan_count`（P7 计数）。
- 每个 (方法, 人格, 信任) 重建 NPC 重放脚本化历史（无 deepcopy sqlite 问题），嵌入同实验 1 用真实端点。

### 实验 3：三配置 × N 扩展

配置：`all_full`（P6 全员全认知 + 门控关，即现系统自治循环原样）/ `tiered`（P8 决策门控开，idle 规则等待）/ `tiered_capped`（tiered + 反思候选证据 `min_relevance` 下限 + top_k 收紧）。世界：稻妻 6 区域 + N 个 NPC（5 原型轮换扩展）+ 1 个 LLM 自治旅行者，3 天 × 8 步（24 步/跑），世界事件逐级升级（眼狩令 → 搜捕 → 清剿）。

- 每 NPC 独立 `RealLLM()` 实例（per-NPC 成本归属），embedder 共享 **HashEmbedder**（嵌入零延迟，不污染 LLM 延迟测量——与实验 1/2 的嵌入选择刻意不同，README 注明）。
- **LLM Calls / Tokens per Step**：P5 计数器按步快照。
- **P50 / P95 Step Latency**：每步计时聚合。**本实验独占 LLM 端点跑**（不与实验 1/2 并发，防排队污染延迟数）。
- **Decision Consistency**：旅行者决策序列逐步比对（action 类型一致率）+ 终局世界状态比对（存活数、旅行者攻值/理由数、将军结局）——多智能体模拟中 NPC 走位会分叉，故关键交互质量量在旅行者这条主线上；另计"漏感知"：NPC 处 idle 时发生的世界事件数 + 两臂自我反思条数差（调度省成本必须明说的代价：远处 NPC 认知深度变浅）。
- **NPC Count Scaling**：tiered 系 N = 5 / 10 / 20 / 40 完整扩展曲线；all_full 只取 N=5 一个线性增长证据点；tiered_capped 取 N=40 单锚点（证据上限的边际收益在大 N 最可见）。**预算修正（跑批中定）**：`decide_action` 是重调用（大 prompt + 结构化生成），all_full 下每 NPC 每步一次——N=5 约 144 次决策调用 ≈ 50 分钟，N=10 翻倍到 ≈ 90 分钟，原 6 配置全范围 ≈ 6 小时不可行。收敛后 7 个配置×N ≈ 3 小时，脚本改增量保存（每配置×N 完成即落盘 runs_partial.json，中断不丢进度）。决策一致性在 N=5 双臂可比（all_full 与 tiered 同 N 的旅行者决策序列逐步一致率）。
- 产出 trade-off 散点：x = 成本降幅，y = 关键交互决策一致率。

## 五、执行顺序与 git 提交规范

提交风格照抄仓库惯例（中文，`<主题>: <改动>; <改动> — <备注>`，不用 feat:/fix: 前缀，主题词如 解耦/引擎/修复/B+ 涌现）。

| 步 | 内容 | 闸门 | commit message |
|---|---|---|---|
| 1 | 包内增量 P1–P7 + `tests/test_eval_flags.py` | 离线测试全绿 + 6 探针全绿（真实 LLM） | `实验基建: 包内加消融开关 (反思证据类型/冲突策略 full|heuristic_decay|off/信任调制/证据相关性下限, 缺省全=现行为) + RealLLM usage 计数 + World 全认知开关 + 规划层计数; 新增离线测试 test_eval_flags, 全量离线测试与 6 探针全绿` |
| 2 | `evals/` 全部文件 | 三脚本 `--smoke` 前台小跑通过 | `实验: 新建 evals/ 评测 harness — 记忆一致性四臂消融/决策消融三方法/认知调度三配置×N扩展, 场景与期望响应表, LLM 裁判与指标共用件; 依赖方向单向 evals→persona_agent, 冒烟通过` |
| 3 | 全量跑批（实验 3 独占 → 实验 1+2 并发）后：结果表回填 `evals/README.md`、`OVERVIEW.md` 验证体系一节挂评测 | 指标可复算、runs.json 在 data/eval/ 下（不入库） | `实验结果: 三实验数据与方法学 — 记忆卫生链四臂对比/效用决策消融/调度 cost-quality trade-off; evals/README 方法学 + OVERVIEW 验证体系挂评测` |

---

## 六、进度清单（完成即勾选）

- [x] P1 reflection.py：evidence_types / conflict_policy / evidence_min_relevance 参数
- [x] P2 reflection.py：check_conflicts 分派 + `_check_conflicts_llm` 迁移 + `_check_conflicts_heuristic` 新增
- [x] P3 npc.py：构造参数透传
- [x] P4 reacting.py：use_relationship 开关
- [x] P5 llm_real.py：usage 计数器 + _stats_tag 透传
- [x] P6 world.py：force_full_tier 开关
- [x] P7 planning.py：daily_plan_count / replan_count
- [x] P8 world.py：decision_tier_gate 决策门控
- [x] tests/test_eval_flags.py 离线测试
- [x] 闸门：离线测试 (当时 138 个用例全绿) + 6 探针 (85s 全绿)
- [x] 提交 1 (044290e 实验基建)
- [x] evals/common.py（NPC 工厂 / 轨迹构造 / 裁判 / 指标 / 落盘）
- [x] evals/scenarios.py（人格×信任×事件矩阵 + 54 格期望响应表）
- [x] evals/memory_consistency.py
- [x] evals/decision_ablation.py
- [x] evals/scheduling_efficiency.py
- [x] evals/README.md 方法学（结果表留空待回填）
- [x] 三脚本 --smoke 冒烟通过（信号符合设计：记忆四臂梯度/决策三方法分化/调度成本阶梯）
- [x] 提交 2 (ec378d2)
- [x] 跑批暴露包缺陷 → 单独修复提交：decide_action 解析失败兜底 wait (e87b4cb, 回归闸门全绿)
- [x] 全量跑批：实验 3（独占；tiered N=20 暴露解析崩溃 → 修复后增量续跑）
- [x] 全量跑批：实验 1（34 分钟）+ 实验 2（19 分钟，并发）
- [x] 结果汇总回填 evals/README 三张表 + OVERVIEW 验证体系挂评测
- [x] 提交 3（结果与文档已入库；复算入口 `data/eval/<实验>/<时间戳>/`）
