# persona_agent 系统总览

一个基于 [Generative Agents](https://arxiv.org/abs/2304.03442) 的**千人千面游戏
NPC 框架**：纯 Python 标准库 + SQLite，真实 LLM（SGLang 部署的
`Qwen3.8-27B-Coder/BF16`）驱动，同一个 NPC 对不同玩家动态变化面孔。核心包约
4,400 行 / 13 个源文件（不含测试、评测、示例与可视化）。

## 一、核心设计：自我 / 面 解耦

这是整个框架的根。NPC 的行为不是单一函数，而是**共享的稳定自我**与**每玩家独立
的关系面**相乘：

```
自我（所有玩家共享, 稳定）
  Persona 特质 + 自我反思 + 世界记忆(player_id=None)

对玩家 p 的面（每玩家独立成流, 动态）
  对 p 的关系记忆 + 对 p 的关系反思 + 对 p 的信任状态

行为 a_t = π(自我, 对p的记忆, 对p的关系反思, 当前计划, 当前情境, p)
```

帮过它的玩家被亲近、骗过它的玩家被警惕、互不污染——同一个 Klaus，对 Aria 热情、
对 Bram 警惕。

P1 社交层把"面"从 per-player 泛化为 **per-entity**：NPC 之间同样有独立的关系记忆、
关系反思与双向信任，机制完全复用，只是 `player_id` 的语义扩展为"关于哪个实体"。

## 二、模块结构

| 模块 | 文件 | 职责 |
|---|---|---|
| 记忆流 + 检索 | `memory.py` | 每条记忆带 `player_id`（per-entity 面）；三维评分（recency/importance/relevance）+ 实体加权；观察去重、降权遗忘、传闻折扣 |
| 反思 | `reflection.py` | 自我反思 / 关系反思 / 身份信念三条轨；证据引用 + 语义去重 + LLM 冲突失效 |
| 规划 | `planning.py` | 日→小时→分钟层次化；plan 作为记忆参与检索；反应后从当前时刻重规划 |
| 反应 | `reacting.py` | 效用函数决策，事件价值 + 关系信任度均由 LLM 判断 |
| 对话 | `dialogue.py` | 非全知：只用"当前对话者的面 + 共享流"，把"对话者是谁"并入检索 |
| 成本闸门 | `npc.py` | 分级认知（full/compressed/idle）+ 决策缓存 + 夜间固化 |
| **游戏世界层** | `world.py` | 多 NPC + 多玩家共存、空间感知、距离调度、世界事件、自治循环、动作钩子、行为链、视觉事件、独立持久化 |
| NPC↔NPC 社交 | `world.py` / `npc.py` | per-entity 记忆流、社交感知、NPC 间信任、谣言按跳数折扣 |
| LLM 层 | `llm.py` / `llm_real.py` | 12 方法抽象接口 + 唯一 RealLLM 实现（OpenAI 兼容） |
| 向量层 | `embeddings.py` / `embeddings_real.py` | HashEmbedder（回退）+ RealEmbedder（gte-Qwen2）+ make_embedder |
| 评测 / 可视化 | `evals/` / `visualization/` | 三组消融实验；Phaser 像素风时间线回放器（含直播跟随） |

## 三、LLM 推理栈——十二类推理全是 LLM 判断

`LLMClient` 抽象出 12 个方法，**过去靠关键词死表的地方现在全部交给 LLM 语义
判断**，每个都配成本闸门：

| 推理 | 方法 | 输出 | 成本闸门 |
|---|---|---|---|
| 对话/反应回复 | `complete` | 文本 | 决策缓存 |
| 记忆重要性 | `score_importance` | 1-10 | — |
| 反思问题 | `reflection_questions` | 3 个高层问题 | 重要性累积阈值门控 |
| 反思洞察 | `reflection_insights` | 带引用的 Insight | 级联切断 + 语义去重 |
| 日计划 | `generate_plan` | 活动列表 | — |
| 活动分解 | `decompose_activity` | 子任务 | — |
| **事件价值** | `score_event` | 社交/目标/打断 各 0-10 | 按 `(事件, 计划)` 缓存 |
| **关系信任** | `judge_trust` | -1..1 | 按关系记忆签名 `(条数, 最新时间戳)` 缓存 |
| **冲突强度** | `judge_conflict` | 0-10 矛盾强度 | 按 `(反思内容, 观察内容)` 缓存 |
| 动作感知 | `perceive_action` | NPC 自己视角的玩家动作描述 | 走 NPC 观察/记忆流 |
| 动作决策 | `decide_action` | 下一步动作 (非全知) | 决策缓存 |
| 记忆固化 | `consolidate_observations` | 情节摘要 | 夜间固化开关 + 每日一次 |

后三个（事件价值/信任/冲突）是从"关键词词表"升级成"LLM 判断"的。收益实测：

- **事件价值**：派对邀请对正在备派对的人目标价值判 8（词表一律给 1）；失火求援、
  商业提案等没枚举过的事件不再落 `DEFAULT_VALUE`。
- **信任**：理解"搭把手=帮""放鸽子跑路=背叛"等词表漏判的花样措辞，且是程度
  判断（搭把手 +0.2 < 修咖啡机 +0.5）。
- **冲突**：语义矛盾取代方向词表，"失联了"算背叛、"帮了大忙"算帮助、一致组合判 0。

统一约束：**非全知原则**——LLM 实现只使用传入的记忆内容，不窥探全局。

## 四、记忆卫生链——每一环都有成本闸门

记忆不失控、不灌水、不丢失，靠一条链：

```
观察去重(0.92, 合并不新增)
  → 反思级联切断(证据只引用观察) + 反思语义去重(0.92)
  → 冲突失效(LLM 判矛盾强度, 强矛盾失效/部分矛盾衰减)
  → 夜间固化(观察压缩成 episode, 退出冲突扫描)
  → 降权遗忘(部分衰减, 不删除)
```

- **观察去重**：同一实体的近义观察（≥0.92）合并进已有记录——刷新 `last_accessed`
  （重复发生=记忆强化）、importance 每 ≥6h 最多 +1，不新增。事件重放不灌水。
- **反思级联切断**：反思找证据限定 `types=["observation"]`，不能拿反思当证据
  （否则一代代复述放大自己）。修掉了"57 条记忆 51 条反思"的失控。
- **反思语义去重**：新洞察与同一条流已有反思余弦 ≥0.92 视为复述，跳过 (E6 从 0.95 下调)。
- **冲突失效**：LLM 判每条反思 × 每条更晚观察的矛盾强度，≥7 失效、3-6 衰减
  置信度、<3 不动。
- **夜间固化**：每天 `consolidate_hour` 把当天观察按流压缩成 `episode`，源观察标
  `consolidated`（仍 valid、可检索，但退出冲突扫描）。摘要置信度取源观察最低值、
  幂等；冲突扫描从"反思 × 全部后续观察"降为线性于信念层大小。
- **降权遗忘**：`importance *= 0.5^(age/half_life)`，渐近到 `MIN_IMPORTANCE`(1.5)
  为止，**记忆保留不删除**，老记忆跌出检索前排、被回忆又能升回。分层半衰期：
  观察 48h（~2 天）/ 反思与 episode 168h（~1 周）/ 身份信念 336h（~2 周）/
  计划 24h（隔夜）。被反思固化的
  观察受保护、被回忆过的衰减更慢。纯本地计算，零 LLM。
- **传闻折扣**：`hearsay=True` 的记忆检索分数按 `0.8^hop` 打折；超过 3 跳不再
  转述。传闻不是亲见，离源头越远排名越低。

## 五、判断型决策栈（反应层）

反应是高频路径，决策 = 人格权重 × 信任调制 × LLM 事件价值：

```
效用 U = w_social(人格×信任) · V_social + w_goal · V_goal − C_interrupt
react 当且仅当 U ≥ 0
```

事件价值判"事"的分量，信任度（记忆派生）单独调制 `w_social`，二者相乘——
**同一句派对邀请，Aria（信任+1）效用 13 接受、Bram（信任-1）效用 -3.4 婉拒**。
这就是反应层的千人千面。

## 六、信任：持久的关系认知（显式设计）

信任度**不随遗忘淡化**——`judge_trust` 只看关系记忆的内容、刻意不看 importance。
遗忘只降权不删除，久远的帮助/背叛仍是认知，帮过的人不会被时间冲淡。真实 LLM
验证：帮助记忆 importance 7.0→1.5 降权后，强制重判信任 +0.50→+0.50 不变。
回归测试 `test_trust_does_not_fade_with_forgetting` 锁定。

## 七、成本管理（blog「问题一」的落地）

四层闸门，让 LLM 开销可控：

1. **分级认知**：近处 NPC 走完整循环（full）、远处压缩更新（compressed）、空闲
   只做记忆（idle）。**档位由距离自动调度**（世界层 `tier_of`）：玩家同区域→full、
   视距内→compressed、远离/离开→idle。近处全认知、远处省认知，自动降档。
   `decision_tier_gate=True` 时 idle NPC 在自治循环里规则等待，零 LLM 决策。
2. **决策缓存**：相同情境复用反应，命中不重复调 LLM（精确键 + LRU 上限）。
3. **推理级缓存**：事件价值/信任/冲突各自按内容签名缓存，重复判断零成本；
   共享冲突检查还额外按"共享证据签名"门控，没有新证据不重扫。
4. **反思门控**：只有出现新观察才重跑关系反思；自我反思只累积共享流观察；
   夜间固化每天每流最多一次，避免反思无限增殖、信任漂移。

## 八、游戏世界层（多 NPC 真实世界）

在单个 NPC 之上加了一个世界层（`world.py`），把"脚本手喂单个 NPC"升级为
**多 NPC + 多玩家在空间世界里自动感知、距离调度认知**：

- **空间与实体**：`Location`（有坐标的区域）/ `Entity` / `Player` / `World`。
  稻妻城 6 区域，5 个 NPC + 1 个脚本驱动旅行者。
- **空间感知**：`World.perceive` 让 NPC 感知视距内的玩家，自动生成观察喂
  `npc.observe()`（替代手写），粒度随档位（full 富细节 / compressed 稀疏 / idle 无）。
- **距离调度**：`World.tier_of` / `schedule_tiers` 按最近玩家距离自动设档——
  近处全认知、远处省认知（blog 问题一落地）。
- **世界事件**：`World.world_event` 共享事件（眼狩令生效 / 执行官搜捕/世界级危机），
  范围内 NPC 半径感知，全图事件影响所有 NPC。
- **双模拟循环**：`World.step` 是"世界推进"（时钟→距离调度→感知→按档反思→遗忘→
  落库）；`World.step_autonomous` 是全自治（所有存活实体先基于同一时刻感知决策，
  再统一执行，然后重感知/反思，重大状态变化触发重规划）。
- **可注入的动作/事件**：`add_action_effect(action, fn)` 注入"这个动作在本世界还
  引发什么"（理由生成/锻刀/世界事件）；`add_chain_rule(action, threshold, desc)`
  让行为链计数触发内生事件。引擎不硬编码具体世界行为。
- **结构化视觉事件**：`VisualEvent` 是渲染层单一事实源（`move/conversation/
  attack/help/hide/flee/wait/world_event`），字符串由 `describe()` 派生。
- **NPC↔NPC 社交**（P1，缺省关）：`social_perception=True` 感知视距内其他 NPC；
  记忆流泛化到 per-entity；`rumor_spread=True` 时对话被第三方听到并转述，形成
  `hearsay/hop` 传闻链（每跳 ×0.8，最多 3 跳）。NPC 间信任双向独立。
- **记忆固化 + 身份信念**（P2，缺省关）：夜间把观察压缩成 episode；自我反思可产出
  跨玩家身份信念并注入自治决策。
- **独立持久化**：世界状态单独存 `world.db`（位置/时钟/NPC 注册表），每 NPC 独立
  `<name>.db`，跨进程恢复整个世界（含各 NPC 记忆与面）。
- **稻妻城·眼狩令 demo**（`examples/world_demo.py`）：5 NPC（桃音/刚郎/小梅 持神之
  眼、执行官、雷电将军）+ 旅行者；自治版 `examples/world_auto_sim.py` 跑 10 天 ×
  8 步，旅行者与将军的胜负/说服结局由交互涌现。

## 九、验证体系

- **6 个集成探针**（`probes.py`，需真实 LLM，不可达自动 skip）：把"它真的千人千面
  了吗"变成对真实 LLM 的回归——一致性（信任不同+回答不同）、非全知（LLM 裁判判
  "是否自信编造"）、持久性（背叛者信任<帮助者）、漂移（人格稳定）、第一人称
  （不自称名字）、**世界隔离（同一玩家对不同 NPC 的面独立、跨 NPC 不污染）**。
  探针 4 的"计划目标导向"目前是关键词判定，对措辞敏感，偶发假阴性。
- **离线测试**（**246 个**，无网络，stub LLM，45 个离线测试文件 + 1 个探针文件）：覆盖记忆卫生
  （去重/证据/固化/遗忘/显著性）、反思流隔离、计划生命周期、反应缓存、成本闸门、
  世界层（骨架/多 NPC/感知/距离调度/世界事件/自治持久化）、社交层/谣言、
  错误隔离与消融开关等架构确定性。连同 6 探针共 **252 个测试**。
- **可视化 E2E**（`visualization/`，`npm run e2e`）：无头 Chromium 验证回放、
  时间轴寻址、气泡/详情卡、像素活动投影、旧格式回退、直播跟随。
- **三实验评测**（`evals/`，需真实 LLM，方法学与结果表见 `evals/README.md`，
  设计记录见 [EvalPlan.md](EvalPlan.md)）：
  1. **记忆一致性四臂消融**（`evals/memory_consistency.py`）：帮助→信任反思→背叛→
     再交互的多轮轨迹，四臂隔离机制——原始反思无矛盾处理 / 证据约束无矛盾处理 /
     原始反思+词表衰减 / 证据约束+LLM矛盾判别+置信度衰减（现系统）。指标：证据
     支撑率、过期记忆召回率、认知冲突率（检索上下文级确定性 + 对话级 LLM 裁判）。
  2. **决策消融三方法**（`evals/decision_ablation.py`）：固定优先级规则 / 无关系权重
     效用 / 人格×关系完整效用，在 3 人格×3 信任档×6 事件矩阵上对拍预先定义的
     期望响应表（忽略低价值事件是正确行为）。指标：ERR、GCR、关系/人格一致性、
     计划打断率。
  3. **认知调度效率**（`evals/scheduling_efficiency.py`）：全员全认知 / 距离三级调度
     +idle 决策门控 / 调度+候选证据限制，稻妻自治世界 N=5→40 扩展。指标：每步
     LLM 调用/token、P50/P95 延迟、旅行者决策一致率、自我反思深度差、NPC 数扩展性
     ——决策质量 ↔ 推理成本的 trade-off 曲线。

## 十、怎么用

```python
from persona_agent import NPC, RealLLM, make_embedder

# 创建或加载持久化 NPC (data/<name>.db, 一个 NPC 一个 SQLite 库)
npc = NPC.create("Isabella", {"social": 0.8, "goal_oriented": 0.3},
                 llm=RealLLM(), embedder=make_embedder(), data_dir="data")

npc.observe("Aria 帮 Isabella 整理了菜单", now=10.0, player_id="Aria")  # 观察(自动去重)
npc.speak("Aria", "你最近忙什么?", now=12.0)                            # 非全知对话
npc.react("Aria 邀请 Isabella 参加派对", "Aria", now=13.0)               # LLM 效用决策
npc.trust_toward("Aria")   # LLM 判的信任度
npc.save()                  # 落库, 跨进程恢复
```

单 NPC 端到端 demo：`python examples/game_loop.py`（Klaus 对 Aria/Bram 的千人千面）。
审查工具：`python tools/inspect_npc.py data/<name>.db`（看记忆流、证据链、相似度）。

世界层 API：

```python
from persona_agent import World, Location, RealLLM, make_embedder

w = World("稻妻城", [Location("主城", 0, 0), Location("治疗堂", 1, 0)],
          path="data/inazuma/world.db")                 # 世界状态独立存 world.db
w.add_npc("桃音", {"social": 0.8, "goal_oriented": 0.3},
          llm=RealLLM(), embedder=make_embedder(),
          data_dir="data/inazuma", location="治疗堂")     # 每 NPC 独立 <name>.db
w.add_player("旅行者", "主城")
w.world_event("雷电将军颁布眼狩令", now=7.0)               # 世界事件, 半径/全图感知
w.step(8.0)                                               # 距离调度 + 感知 + 反思 + 落库
w.npc("桃音").trust_toward("旅行者")                       # 千人千面: 各 NPC 独立的面
w.save()                                                  # 跨进程恢复整个世界
```

多 NPC 真实世界 demo：`python examples/world_demo.py`（稻妻城·眼狩令：5 NPC + 旅行
者，距离调度、千人千面、世界事件）。

## 十一、不变式（始终守住）

自我/面解耦 · 每实体独立记忆流 · 非全知 · 信任调制效用 · 反思门控 · 固化保护 ·
证据只引用观察 · 降权不删除 · 传闻按跳数折扣 · **跨 NPC 记忆隔离**（每 NPC 独立
记忆流，不互相污染）· **距离调度认知**（近处全认知、远处省认知，档位由距离自动推导）。

## 十二、当前状态

- **核心机制已落地**：反思去重、观察去重、降权遗忘、LLM 反应决策、LLM 信任度、
  LLM 冲突失效、持久化、夜间固化（episode）、身份层信念。
- **游戏世界层完成**：7 阶段全部落地，多 NPC + 多玩家空间共存、空间感知、距离调度
  档位、世界事件、双模拟循环、动作效果钩子、行为链事件、结构化视觉事件、独立
  持久化。blog「问题一」（距离→档位自动调度）已由世界层阶段 3 解决，不再手动
  `set_tier`。实施记录见 **[WorldPlan.md](WorldPlan.md)**。
- **NextPlan P1/P2 完成**：NPC↔NPC 社交层 + 谣言（per-entity 面、社交感知、
  hearsay 跳数折扣、内生事件）；记忆固化 + 身份信念（episode 吸收旧观察、冲突扫描
  线性化、跨玩家信念注入决策）。**P3 关系阶段/修复/称呼、P4 idle 自治仍待做**。
- **自治世界已跑通**：`examples/world_auto_sim.py`（10 天 × 8 步，5 NPC + 旅行者）
  以真实 LLM 跑出完整弧线，结局由旅行者与将军的交互涌现（战斗或说服），无脚本门控；
  回放产物在 `data/auto_sim/timeline.json`。
- **稻妻城·眼狩令 demo**（`examples/world_demo.py`）已用真实 LLM 跑通：距离调度档位
  全对、信任千人千面（受助高/务实中/藏匿警惕/疏离零）、眼狩令全图事件、执行官半径
  搜捕、非全知对话。
- **验证与可视化**：246 离线测试全绿；6 探针需端点（漂移探针偶有措辞假阴性）；
  三组消融结果已登记；Phaser 回放器 M0–M5 已实现并 E2E 验证（含旧格式回退与直播跟随）。
- **后续可扩展**：NextPlan P3/P4、AutoSimPlan 阶段 3（NPC 互相求助/结盟对抗/
  集体逃跑）、更多区域与 NPC、多玩家对抗。
