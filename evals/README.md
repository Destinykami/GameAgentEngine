# evals/ — 三实验评测方法学

评测 persona_agent 的三个核心机制：**记忆卫生链**（证据约束反思 + LLM 矛盾判别 +
置信度衰减）、**判断型决策栈**（人格 × 关系的效用决策）、**分级认知调度**
（距离档位 + 决策门控 + 候选证据限制）。设计总原则与包内改动映射（P1–P8）见
[EvalPlan.md](../EvalPlan.md)。

依赖方向：`evals → persona_agent` 单向；harness 只通过公开 API 观察，无
monkeypatch。运行产物落 `data/eval/<实验>/<时间戳>/`（被 .gitignore 挡住），
只有本文档的结果表入库。

## 实验 1 — 记忆一致性四臂消融 (`memory_consistency.py`)

| 臂 | 反思机制 | 矛盾处理 | 隔离的机制 |
|---|---|---|---|
| baseline | 原始反思（证据可引用反思） | 无 | Generative Agents 基线 |
| ablation_a | 证据约束反思（级联切断） | 无 | 证据约束本身 |
| ablation_b | 原始反思 | 词表方向矛盾，只衰减不失效，零 LLM | 衰减机制本身 |
| ours | 证据约束反思 | LLM 判矛盾强度：≥7 失效 / 3–6 衰减 | 完整记忆卫生链 |

轨迹（每臂 10 条，措辞语义多样化防观察去重误并）：帮助观察 t0–4 → 关系反思 t6
（产出 **stale 集**：背叛前形成的信任类反思）→ 背叛观察 t8–10 → 关系反思 t12
（矛盾处理生效）→ 再交互 t20（检索 + 对话）。

指标口径：

- **Evidence Grounding Rate (EGR)**：反思的证据 id 全指向 observation 的比例，
  读库确定性计算（含失效反思，证据链可审计）。ours/ablation_a 结构性 100%，
  baseline/ablation_b 的 <100% 即级联失控的量化。
- **Stale Memory Recall Rate**：t20 关系相关查询 top-8 中 stale 集的占比与平均排名。
  被**失效**的反思（valid=0）进不了检索，ours 臂趋 0 是机制使然（如实报）；
  有效信号在 baseline/a（过期但 valid，高召回）vs ablation_b（衰减后被置信度
  乘数压排名）。
- **Contradiction Rate** 两级：context 级（确定性）——top-8 同时含 stale 信任断言
  与背叛观察，即"同一关系两种判断并存"；utterance 级（LLM 裁判 YES/NO，
  temperature=0）——t20 回复是否对同一人同时主张信任与背叛。
- 附带：背叛后信任度、失效反思条数、每臂 LLM 调用数（成本对照）。

嵌入用真实 gte-Qwen2（`make_embedder`）——HashEmbedder 是词面哈希，"过期召回"
的语义相似度会失真。

## 实验 2 — 决策消融三方法 (`decision_ablation.py` + `scenarios.py`)

| 方法 | 决策机制 |
|---|---|
| fixed | 关键词固定优先级：危险 > 求助 > 社交 > 继续计划（无 LLM、无信任输入） |
| no_relationship | 效用决策但信任调制关闭（`trust_mod` 钉死 1.0） |
| full | 现系统：`U = w_social(人格×信任)·V_social + w_goal·V_goal − C_interrupt`，事件价值 LLM 判断 |

场景矩阵：3 人格（社交/平衡/目标）× 3 信任档（高信任=3 次相助 / 中立=一面之缘 /
低信任=失信背叛）× 6 事件（藏匿求助/派对邀请/低价值闲聊/敌对威胁/委托打铁/
再求助）。**期望响应表按人格×关系逻辑预定义**（`scenarios.py` 逐条注释）——
事件响应率不是越高越好：忽略低价值闲聊恰是正确行为。每场景重建 NPC（真实 LLM
重放信任历史 + 日计划），错误响应中断类事件触发重规划（镜像世界层
INTERRUPT_ACTIONS 语义）。

指标：

- **ERR**：决策与期望表一致率。
- **GCR**：日计划存活率（无错误中断 → 无重规划）。
- **Relationship Consistency**：同事件高/低信任对的响应分化（高分侧接受且低分侧拒绝）。
- **Persona Consistency**：同事件人格对按期望分化（社交型接派对、目标型接委托）。
- **Plan Disruption Rate**：重规划次数 / 日计划次数（P7 计数）。
- LLM 裁判软评分（party/forge 子集）：决策理由与人格/关系的一致性。**未做人工
  校准**——同族模型裁判，只作辅助信号，不替代确定性指标。

固定优先级基线不看信任输入（它没有这个能力）——low 信任场景下的"照单全收"正是
该消融要量化的缺陷。

## 实验 3 — 认知调度效率 (`scheduling_efficiency.py`)

| 配置 | 认知调度 | 决策门控 | 候选证据限制 |
|---|---|---|---|
| all_full | 全员 full（P6） | 关（每 NPC 每步 LLM 决策） | 无 |
| tiered | 距离三级调度 | 开（idle NPC 规则等待，零 LLM，P8） | 无 |
| tiered_capped | 距离三级调度 | 开 | 反思证据相关性下限 0.5（P1） |

世界：稻妻 6 区域 + N 个 NPC（将军唯一，4 原型轮换扩展）+ LLM 自治旅行者，3 天
× 8 步，世界事件逐级升级。每 NPC 独立 `RealLLM` 实例 → usage 计数器天然 per-NPC
归属；**嵌入用 HashEmbedder（零延迟，不污染 LLM 延迟测量**——与实验 1/2 刻意不同）。

指标：LLM Calls / Tokens per Step（P5 计数器按步差分）、P50/P95 Step Latency
（每步计时）、by_method 成本拆解、Decision Consistency（同 N 下 all_full vs
tiered 的旅行者决策序列逐步一致率 + 终局世界状态比对）、认知深度代价（自我反思
条数差——idle NPC 不累积重要性故不自我反思，这是省成本必须明说的代价）、
NPC Count Scaling（all_full 封顶 N≤10，tiered 系跑到 N=40）。

**trade-off 主张**：tiered 臂每步成本应近似常数（远处 NPC 零决策调用），而关键
交互（旅行者与近处 NPC）的决策质量基本保持。已知边界：每日早晨的计划生成波
（每 NPC 一次 generate_plan）不受档位门控，N 大时是 tiered 臂的主要固定开销——
如实报告在 by_method 拆解里。

## 跑法

```bash
.venv/bin/python evals/memory_consistency.py --smoke      # 每臂 1 条, ~2 分钟
.venv/bin/python evals/memory_consistency.py              # 全量, ~30-40 分钟
.venv/bin/python evals/decision_ablation.py --smoke       # 1 人格×信任切片, ~3 分钟
.venv/bin/python evals/decision_ablation.py               # 全量, ~60 分钟
.venv/bin/python evals/scheduling_efficiency.py --smoke   # N=2×2步, ~2 分钟
.venv/bin/python evals/scheduling_efficiency.py           # 全量, ~45-60 分钟
```

实验 3 测延迟，**必须独占 LLM 端点跑**（不与 1/2 并发，防排队污染 P50/P95）。
端点不可达时脚本 fail fast（不 skip——评测硬依赖真实 LLM）。

## 结果

（全量跑批完成后回填：三张指标表 + trade-off 结论。runs.json/metrics.json 在
`data/eval/<实验>/<时间戳>/`，复算入口。）

- 实验 1（四臂 × 10 轨迹）：
- 实验 2（三方法 × 54 场景）：
- 实验 3（三配置 × N∈{5,10,20,40}，all_full 封顶 N≤10）：
