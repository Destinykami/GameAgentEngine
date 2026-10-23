# game_agent — 千人千面游戏 NPC 框架

> 重构设计入口：**[docs/README.md](docs/README.md)**，包含按当前代码核对的系统总览、模块蓝图划分、重构路线与设计模板。
>
> 当前源码采用 **[src/game_agent](src/game_agent/)**，按认知、记忆、世界、模型和评测探针分组；[源码布局](docs/source-layout.md) 说明安装与导入契约，仅支持 `game_agent` 包路径。原 [OVERVIEW.md](OVERVIEW.md) 保留重构前的机制说明与历史状态。

基于 [Generative Agents: Interactive Simulacra of Human Behavior](https://arxiv.org/abs/2304.03442)
的思路, 构建能随玩家互动历史**动态变化面孔**的游戏 NPC。

核心设计 (详见配套 blog): **自我** 与 **面** 解耦。

```
NPC 的自我 (所有玩家共享, 稳定)
  Persona  +  自我反思  +  世界记忆 (player_id=None)

NPC 对玩家 p 的面 (每玩家独立成流, 动态)
  对 p 的关系记忆  +  对 p 的关系反思  +  对 p 的信任状态

行为 a_t = π(自我, 对p的记忆, 对p的关系反思, 当前计划, 当前情境, 玩家p)
```

同一个 NPC: 帮过它的玩家被亲近, 骗过它的玩家被警惕, 互不污染。

## 模块映射 (论文 → 本框架)

| 论文模块 | 文件 | 为千人千面扩展了什么 |
|---|---|---|
| Memory Stream + Retrieval | `src/game_agent/memory/store.py` | 每条记忆带 `player_id`; 检索三维评分 (recency/importance/relevance) 之外, 对当前玩家记忆加权 |
| Reflection | `src/game_agent/cognition/reflection/` | 自我、关系与身份反思；生成编排、证据写入和冲突处理分开，设计见 [反思蓝图](docs/modules/reflection.md) |
| Planning | `src/game_agent/cognition/planning/` | 日计划及一次子任务分解、反应后重规划；时间规则、计划记忆与当前状态分开，见 [规划蓝图](docs/modules/planning.md) |
| Reacting | `src/game_agent/cognition/reacting/` | 评分、关系信任、纯效用策略和缓存职责分开，保留人格权重与信任调制，见 [事件反应蓝图](docs/modules/reaction.md) |
| Dialogue | `src/game_agent/cognition/dialogue/` | 检索“当前对话者的面 + 共享流”；上下文、生成与轮流发言分开，见 [对话蓝图](docs/modules/dialogue.md) |
| 成本闸门 (blog 问题一) | `src/game_agent/cognition/npc.py` | 分级认知 (full/compressed/idle) + 决策缓存 |
| 记忆卫生链 | `src/game_agent/memory/store.py` / `src/game_agent/cognition/reflection/` | 观察去重、级联切断、语义去重、LLM 冲突失效、降权遗忘、夜间情节固化 (episode) |
| NPC↔NPC 社交层 | `src/game_agent/world/runtime.py` / `src/game_agent/cognition/npc.py` | 记忆流从 per-player 泛化到 per-entity; NPC 互相感知、关系反思、信任; 谣言按传播跳数折扣 |
| **游戏世界层** | `src/game_agent/world/runtime.py` | 多 NPC + 多玩家空间共存、空间感知、**距离自动调度档位**、世界事件、自治模拟、动作效果钩子、行为链事件、结构化视觉事件、独立持久化 |
| 评测与可视化 | `evals/` / `visualization/` | 三组消融实验; Phaser 像素风时间线回放器 (含直播跟随) |

## LLM / 向量层

- `game_agent.models.llm.LLMClient`: 抽象接口, **十二个方法** `complete / score_importance /
  reflection_questions / reflection_insights / generate_plan / decompose_activity /
  score_event / judge_trust / judge_conflict / perceive_action / decide_action /
  consolidate_observations`。实现者只应使用传入的记忆内容 (非全知原则)。
- `game_agent.models.llm_http.RealLLM`: 唯一实现, 通过 OpenAI 兼容接口 (`/v1/chat/completions`)
  接入 SGLang 部署的 `Qwen3.8-27B-Coder/BF16`。要换别的 OpenAI 兼容端点,
  改 `base_url` / `model` 即可。
- `game_agent.models.embeddings.Embedder`: 可插拔向量接口, 两个实现:
  - `HashEmbedder` (默认回退): 词袋哈希, 余弦相似度反映**词面重叠**, 确定性、
    零依赖。中文按单字、英文按词分词。
  - `game_agent.models.embeddings_http.RealEmbedder`: 接 OpenAI 兼容 `/v1/embeddings`, 默认指向
    SGLang 部署的 `Alibaba-NLP/gte-Qwen2-1.5B-instruct` @ `10.121.39.10:30006`
    (1536 维, 语义相似度 —— 换说法的同义句也能高相似)。
  - `make_embedder()`: 优先真实端点, 不可达自动回退 HashEmbedder。示例默认用它。

## 运行

Python >= 3.10，运行时仅使用标准库。先从项目根目录安装开发包：

```bash
python -m pip install -e '.[dev]'
# 已有 .venv 时也可使用：
uv pip install --python .venv/bin/python -e '.[dev]'

# 当前真实模型 API 不可达，以离线测试验收：
python -m pytest tests/ --ignore=tests/test_probes.py -q
```

下方真实模拟和在线评测需要 LLM 端点可达（默认 10.121.39.10:30005），当前暂不运行。

```bash
# 端到端 demo: 真实语言模型驱动同一个 Klaus 对 Aria 与 Bram 的千人千面
python examples/demo_real.py

# 单 NPC 完整游戏分钟 (规划/观察/对话/反应/重规划)
python examples/game_loop.py
python examples/persistence.py          # 两次会话的跨进程往返
python examples/forgetting.py           # ~8 天时间跳跃后的分层降权

# 世界层: 脚本驱动旅行者 / 全自治多智能体
python examples/world_demo.py           # 稻妻城·眼狩令, 5 NPC + 旅行者
python examples/world_auto_sim.py       # 10 天 × 8 步, 所有实体都由 LLM 决策

# 完整测试入口（含 6 个真实 LLM 探针；当前仅运行上面的离线测试命令）
pytest tests/ -q

# 评测 (需真实 LLM; 方法与结果见 evals/README.md)
python evals/memory_consistency.py --smoke
python evals/decision_ablation.py --smoke
python evals/scheduling_efficiency.py --smoke

# 可视化回放器
cd visualization && npm install && npm run dev
```

## 反思质量 (级联切断 + 语义去重)

两个曾导致"57 条记忆里 51 条反思"失控的机制, 已修:

1. **级联切断**: 反思找证据时限定 `types=["observation"]` —— 反思只能由真实
   观察支撑, 不能拿别的反思当证据 (否则一代代复述放大自己)。
2. **语义去重**: `ReflectionWriter.save` 保存前, 新洞察与同一条流已有反思做
   余弦比对, `>= 0.92` 视为同一条认知的复述, 跳过不入库。阈值来自
   gte-Qwen2 实测: 措辞不同的重复稳定落 0.85~0.94, 不同面向的独立洞察
   多 <= ~0.90; E6 从 0.95 下调到 0.92 (0.95 在真实数据几乎不生效)。

效果: 2 条观察 → 4 条互不重复的反思 (两两相似度最高 0.92), 证据全指向观察。
用 `python tools/inspect_npc.py data/<name>.db` 可审查证据链与相似度。

## 接入 LLM (RealLLM)

`src/game_agent/models/llm_http.py` 的 `RealLLM` 通过 OpenAI 兼容接口接入
SGLang 部署的 `Qwen3.8-27B-Coder/BF16`:

```python
from game_agent import NPC, RealLLM, HashEmbedder
npc = NPC("Klaus", {"social": 0.4, "goal_oriented": 0.8},
          llm=RealLLM(),                # 默认 http://10.121.39.10:30005
          embedder=HashEmbedder())
```

要点:
- **思考型模型**: 用 SGLang 的 `chat_template_kwargs={"enable_thinking": ...}`
  按调用开关思考。对话/打分默认关思考 (快), 结构化 JSON 任务 (反思/规划) 恒关
  思考 —— 思考 token 会挤爆 `max_tokens` 导致 JSON 截断。`enable_thinking=True`
  可让对话开思考。
- **结构化输出**: 反思问题/洞察、日计划、活动分解都要求模型返回严格 JSON,
  `_extract_json` 容忍 markdown 围栏与前后杂字, 解析失败自动重试一次。
- **非全知**: 对话 prompt 只把检索到的记忆喂给模型, 没检索到就答"没印象"。
- **无依赖**: 用标准库 `urllib` 发请求, 不引入 openai/requests。

## 持久化 (NPC 落库)

默认 NPC 是**内存态**的 (进程退出即失忆)。要持久化, 用 `NPC.create` /
`NPC.load`, 记忆流与元数据存于 `data/<name>.db` (一个 NPC 一个 SQLite 库):

```python
from game_agent import NPC, RealLLM, make_embedder

# 创建或加载 (不存在则新建并落库, 已存在则等价于 load)
isabella = NPC.create("Isabella", {"social": 0.8, "goal_oriented": 0.3},
                      llm=RealLLM(), embedder=make_embedder(), data_dir="data")
isabella.observe("Aria 帮 Isabella 整理了菜单", now=10.0, player_id="Aria")
isabella.save()

# 之后任何时候 (新进程也行) 加载, 记忆流 + 信任状态 + 游戏时钟全部恢复
isabella2 = NPC.load("data/Isabella.db", llm=RealLLM(), embedder=make_embedder())
isabella2.trust_toward("Aria")   # +1.00, 与上次一致
```

- 持久化的内容: 全部记忆流 (观察/反思/计划)、信任状态 (由记忆派生)、游戏时钟。
- `save()` 只写元数据 (名称/人格/时钟), 记忆流落库即持久, 无需额外同步。
- 向量不入库: `HashEmbedder` 确定性、`RealEmbedder` 端点稳定, 加载后向量缓存
  按需重建, 检索结果一致。
- 同一 .db 同一时刻只应被一个进程打开 (未做并发写锁)。

`python examples/persistence.py` 演示两次游戏会话的跨进程往返。

## 游戏世界层 (多 NPC 真实世界)

在单个 NPC 之上加了一层**世界层** (`src/game_agent/world/runtime.py`)，把"脚本手喂单个 NPC"升级为
**多 NPC + 多玩家在空间世界里自动感知、距离调度认知**：

- **空间与实体**：`Location`(有坐标区域) / `Entity` / `Player` / `World`。距离用
  欧氏度量 `distance(a, b)`。
- **多 NPC 共存**：`World.add_npc(name, persona, llm, embedder, data_dir, location)`
  复用 `NPC.create`，每 NPC 独立 db，各自独立记忆流与面，跨 NPC 不污染。
  `add_player` 登记玩家实体。
- **空间感知**：`World.perceive(npc, now)` 让 NPC 感知视距内的玩家，自动生成
  自然语言观察喂 `npc.observe()`（替代手写），粒度随档位：full=富细节、
  compressed=稀疏、idle=无。重复感知同一在场走既有观察去重，不灌水。
- **距离调度**：`World.tier_of(npc)` 按最近玩家距离自动推导档位——同区域
  (≤full_radius) → full、视距内 (≤perception_radius) → compressed、远离/无玩家 →
  idle。`schedule_tiers` 给所有 NPC 自动设档。**这就是 blog「问题一」的落地：
  认知开销随距离自动降档，不再手动 `set_tier`。**
- **世界事件**：`World.world_event(desc, now, at, radius)` 共享事件（眼狩令生效/
  执行官搜捕），范围内 NPC 作为世界观察（不带 player_id）半径感知；`at=None`
  全图事件影响所有 NPC。
- **模拟驱动**：`World.step(now)` 是"世界推进"循环——时钟→距离调度→空间感知→
  按档自我反思→遗忘清扫→自动落库；`World.step_autonomous(now)` 则是**全自治**循环：
  所有存活实体先基于同一时刻感知各自决策，再统一执行，然后重感知/反思。
- **动作与规则可注入**：引擎只负责动作空间与物理规则（移动/伤害/历史/视觉事件），
  具体世界行为经 `add_action_effect(action, fn)` 钩子注入；`add_chain_rule(action,
  threshold, desc)` 让"同一 actor 对同一 target 连续 N 次同类动作"触发世界事件，
  是脚本注入之外的第二条事件来源。
- **结构化视觉事件**：`VisualEvent` 是渲染层的单一事实源（`move/conversation/
  attack/help/hide/flee/wait/world_event`），中文描述由 `describe()` 派生，
  前端不再解析事件串。
- **独立持久化**：世界状态单独存 `world.db`（实体位置+时钟+NPC 注册表），与每
  NPC 的独立 `<name>.db` 分离，不破坏"一 NPC 一库"。`World.load(llm, embedder)`
  跨进程恢复整个世界（含各 NPC 记忆流与面）。

```python
from game_agent import World, Location, RealLLM, make_embedder
w = World("稻妻城", [Location("主城", 0, 0), Location("治疗堂", 1, 0)],
          path="data/inazuma/world.db")
w.add_npc("桃音", {"social": 0.8, "goal_oriented": 0.3},
          llm=RealLLM(), embedder=make_embedder(), data_dir="data/inazuma",
          location="治疗堂")
w.add_player("旅行者", "主城")
w.world_event("雷电将军颁布眼狩令", now=7.0)
w.step(8.0)                        # 距离调度 + 感知 + 反思 + 落库
w.npc("桃音").trust_toward("旅行者")  # 千人千面
```

`python examples/world_demo.py` 演示稻妻城·眼狩令真实世界（5 NPC + 旅行者，
距离调度、千人千面、世界事件）。

## NPC↔NPC 社交层 + 谣言传播 (P1)

千人千面不只对玩家生效：记忆流从 per-player 泛化到 **per-entity**，NPC 之间也能
互相感知、形成关系反思与信任（`player_id` 现在语义是"关于哪个实体的面"，
`None` 仍是共享流）。

- **社交在场感知**：`World(social_perception=True)` 让 NPC 感知视距内其他 NPC 的
  出现，按档位生成观察（full=富细节 / compressed=仅在场 / idle=无）。过渡驱动：
  只对新进入视距的对象产生观察，重复在场不灌水。
- **双向独立**：A 对 B 的信任与 B 对 A 的信任是两条独立的流，互不污染。
- **谣言传播**：`World(rumor_spread=True)` 下，对话会被范围内第三方听到（hop=1），
  持有传闻的 NPC 会继续转述（hop+1）。传闻记忆带 `hearsay` / `hop` 标记，检索分数按
  `0.8^hop` 折扣；`HEARSAY_MAX_HOP=3`，超过三跳不再转述。信任判断里传闻显式标注
  跳数，避免"听来的一句话"与亲眼所见同权。
- **内生事件**：行为链计数达到阈值时经 `world_event` 触发世界事件（如执行官连续
  搜捕失败→署内问责），来源从脚本变为行为。

这些开关**缺省全关**，不改变原行为；回归测试在
[`tests/test_social_layer.py`](tests/test_social_layer.py) 与
[`tests/test_rumors.py`](tests/test_rumors.py)。

## 记忆固化 + 身份层信念 (P2)

- **夜间固化**：`World(consolidation=True)` 在每晚 `consolidate_hour`（默认 23:00）
  把当天的原始观察按流压缩成情节摘要 `episode`，源观察标 `consolidated`（仍 valid、
  可检索，但退出冲突扫描）。摘要置信度取源观察最低值，幂等（同日重跑不重复压缩）。
  这让冲突扫描从"反思 × 全部后续观察"的二次复杂度降为线性于信念层大小。
- **身份层信念**：`World(use_identity_beliefs=True)` 让自我反思产出**跨玩家泛化**的
  身份信念（`type=identity`，写共享流），并在 `decide_agent` 的决策上下文里注入，
  对所有玩家生效。开关缺省关，测试见
  [`tests/test_consolidation.py`](tests/test_consolidation.py)。

## 自治世界与结构化视觉事件

`examples/world_auto_sim.py` 把"脚本驱动旅行者"升级为**全自治**：旅行者、5 个 NPC
（桃音/刚郎/小梅/执行官/雷电将军）各自有 `goal`，每步「感知（非全知）→
`decide_action` → 执行」。剧本只给初始世界和时间推进，走位/台词/动作/结局都由
交互涌现；旅行者可以用证据说服将军，也可以战斗，结局不预设。

一步的流程（`World.step_autonomous`）：

```
距离调度 → 早晨日计划 (每人一次) → 夜间固化 (可选)
  → 所有存活实体基于同一时刻感知决策 (idle 可规则等待, 零 LLM)
  → 统一 execute_action (原子性: 认知事件成功才提交物理状态)
  → 重大状态变化触发 replan → 重感知/反思 → flush 社交交互 → 落库
```

每次动作产出 `VisualEvent`，由 `examples/replay.py` 在终端回放，也是
`visualization/` 的唯一数据源。产物在 `data/auto_sim/`（`timeline.json` +
`world.db` + 每 NPC 独立 db）。

## 可视化回放器

[`visualization/`](visualization/README.md) 是基于 **Phaser + Vite + TypeScript** 的
稻妻城像素风**只读**回放器：消费引擎产出的结构化 `visual_events`，支持播放/暂停/
逐步/调速、时间轴拖拽寻址、对话气泡、伤害数字、点击实体详情卡、活动动画投影；
既能加载跑完的 `timeline.json`，也能用 `?live` 轮询 `live.jsonl` 边跑边看。
回放器不反向修改世界状态，也不根据动画帧重新触发 Agent 决策。

## 评测 (evals/)

三组实验，方法学与结果表见 [`evals/README.md`](evals/README.md)，设计记录见
[EvalPlan.md](EvalPlan.md)：

1. **记忆一致性四臂消融** (`memory_consistency.py`)：baseline / 证据约束 /
   启发式衰减 / 完整链。指标：证据支撑率 (EGR)、过期记忆召回率、认知冲突率。
2. **决策消融三方法** (`decision_ablation.py`)：固定优先级 / 无关系权重效用 /
   完整人格×关系效用，在 3 人格×3 信任档×6 事件矩阵上对拍期望响应表。
3. **认知调度效率** (`scheduling_efficiency.py`)：all_full / tiered / tiered_capped，
   在稻妻自治世界上测每步 LLM 调用/token、P50/P95 延迟、决策一致性、N=5→40 扩展性。

## 六个探针 (集成测试)

`src/game_agent/evaluation/probes.py` 把"它真的千人千面了吗"变成对真实 LLM 的集成回归。每个探针混合
**确定性架构断言** (信任度差异、特质稳定, 不依赖 LLM 措辞) 与 **宽松真实 LLM
断言** (对话不同、非全知不编造、计划目标导向, 对措辞鲁棒)。需 LLM 可达,
不可达时 `pytest` 自动 skip。当前 **332 个离线测试已通过**；以下 6 个探针保留，因真实 API 不可达，本轮未执行：

1. **一致性探针** — 对两个玩家信任度不同, 且同一问话回答不同。
2. **非全知探针** — 没观察过的玩家, 不应自信编造其背叛。判定用 **LLM 裁判**
   (`RealLLM.ask`) 而非关键词: 中文否定式 (没偷过/偷没偷/没什么印象/没留意过)
   关键词判不了, 交给 LLM 判"是否自信断言具体事实"。
3. **持久性探针** — 被背叛后, 对背叛者的信任仍低于对帮助者 (相对断言)。
4. **漂移探针** — 人格特质随时间稳定, 生成的计划仍由 persona 驱动。
   已知限制: "计划目标导向"目前用关键词表判定, 对 LLM 措辞敏感 (如"整理物资/
   制定突发预案"是目标导向但不含预设词), 偶发假阴性。
5. **第一人称探针** — 记忆流是第三人称叙述, NPC 开口时不该用自己的名字称呼
   自己 (防"梳理和 Isabella 的协作流程"式自指 bug)。对话 prompt 里显式把
   记忆中的 NPC 名字映射为"我"。
6. **世界隔离探针** — 同一玩家对不同 NPC 的面独立: 帮过的 NPC 信任为正、骗过的
   为负, 且该 NPC 的记忆流不含另一个 NPC 的交互 (跨 NPC 不污染)。验证世界层的
   多 NPC 千人千面。

## 遗忘 / 衰减 (部分衰减降权, 不删除)

记忆不是只增不减的, 但也不会被抹掉。`src/game_agent/memory/store.py` 的 `decay_and_forget` 按时间
**下调 importance** (降权), 渐近到 `MIN_IMPORTANCE`(1.5) 为止 —— 记忆**保留**
(valid 恒 1), 只是检索权重降低, 老记忆自然跌出前排, 被回忆又能升回:

```
importance *= 0.5 ** (age / half_life)      # 渐近降到 MIN_IMPORTANCE, 不删除
age   = now − max(timestamp, last_accessed)  # 被回忆过 → 衰减更慢
```

- **分层半衰期** (按游戏内小时): 原始观察 48h (~2 天) 最先降权, 反思与情节摘要
  168h (~1 周), 身份信念 336h (~2 周), 计划 24h (隔夜即降权)。
- **保护**: 被有效反思引用为证据的观察不降权 —— 已固化为高阶认知, 降了会削弱
  反思的证据链。保护集在每次清扫前按当前有效反思快照计算。
- **回忆强化**: `last_accessed` 被检索/merge 时刷新, 近期被用到的记忆衰减更慢。
- **触发**: NPC 游戏时钟每推进 6h 自动清扫 (纯本地计算, 零 LLM 成本), 也可
  `npc.forget(now)` 手动触发。
- **与信任的关系 (显式设计)**: 信任是**持久的关系认知**, `judge_trust` 只看
  关系记忆的**内容**、刻意不看 importance。遗忘只降权不删除, 久远的帮助/
  背叛仍是认知 —— 故**信任度不随遗忘淡化**, 帮过的人不会被"时间冲淡"。
  (若想要"关系会淡"的效果, 需把降权后的权重一并喂给 `judge_trust`, 当前
  刻意不做。)

`python examples/forgetting.py` 演示 ~8 天时间跳跃后的分层降权 (importance
前后对比, 受保护帮助不变、杂事触底但保留)。

## 观察去重 (事件重放不灌水)

`npc.observe()` 入库前, 用 embedder 与**同一条流**（同玩家/同实体）的近期观察做
语义比对 (`OBS_DEDUP_THRESHOLD = 0.92`, 与反思去重同阈值, 观察更公式化、
近义重复更多)。近义则**合并**而非跳过:

- 不新增记录, 返回已有观察的 id (反思证据引用不断)。
- 刷新 `last_accessed` —— 事件反复发生 = 记忆强化, 衰减锚点后移, 抗遗忘。
- importance 最多每 6h 强化 +1 (上限 10; `MERGE_REINFORCE_INTERVAL`) ——
  反复发生的事件更突出, 但不会因每步在场被顶满。

效果: 事件重放不再灌水 —— 信任度不被重复计分, 重要性累积不被反复抬高,
检索 top_k 不被重复记忆占满。限定同一条流: 跨玩家/跨实体的相似文本是不同关系,
不合并。

## 反应决策 (LLM 判断事件价值)

反应决策不再查关键词死表。`ReactionDecider` 把事件价值判断交给 LLM
(`LLMClient.score_event` → `RealLLM` 严格 JSON, 关思考): 给定事件 + 人格 +
当前计划, 判出 `(社交价值, 目标价值, 打断代价)` 各 0-10。

- **能反应任意事件**: 没枚举过的 (失火求援/商业提案/看护病猫) 也能被正确权衡,
  不再一律落 `DEFAULT_VALUE`。且会参考当前计划 —— 派对邀请对正在备派对的人
  目标价值高。
- **成本闸门**: 事件价值按 `(事件, 计划)` 缓存, 同一情境不重复调 LLM; 加上
  `npc.react` 的决策缓存 (精确键 + 上限), 反应路径的 LLM 开销可控。
- **信任仍独立调制**: 事件价值是"事"的分量, 信任度(记忆派生)单独调制
  `w_social`, 二者相乘 —— 同一派对, 对信任者接受、对背叛者拒绝。

## 信任度 (LLM 判断, 取代词表)

`ReactionDecider.relationship_trust` 不再数关键词, 改为让 LLM 基于该玩家
的全部关系记忆 (观察 + 反思) 判断信任度 `-1..1` (`LLMClient.judge_trust`)。

- **理解花样措辞**: "搭把手"=帮、"接济"=帮、"放鸽子/拿钱跑路"=背叛, 这些词表
  漏判的说法 LLM 都能判对 (实测 +0.2/+0.5/-1.0)。且是**程度判断** (搭把手 +0.2
  < 修咖啡机 +0.5), 比词表二值 ±1 更细腻。
- **成本闸门 (签名缓存)**: 信任是高频读取 (`react` 建缓存键就要用), 不能每次
  调 LLM。按玩家缓存, 失效键 = 关系记忆签名 `(条数, 最新时间戳)` —— 只有该
  玩家的关系记忆真正变化 (新增观察/反思、被遗忘) 才重判, 否则命中缓存零成本。

## 冲突失效 (LLM 判矛盾强度, 取代词表)

`ReflectionEngine.check_conflicts` 不再数"信任词 vs 背叛词", 改为让 LLM 判
**矛盾强度 0-10** (`LLMClient.judge_conflict`): 对每条反思 × 每条**更晚**的观察,
判"这条新观察与旧反思矛盾吗、多强"。

- **语义矛盾**: 强背叛推翻强信任 = 高分 → 反思失效; 轻微帮助削弱轻微警惕 =
  中分 → 置信度衰减。只查更晚的观察 (时间上只有新证据能推翻旧信念)。
- **成本闸门**: 判断按 `(反思内容, 观察内容)` 缓存, 重复检查同一对零 LLM 成本;
  且 `check_conflicts` 由 `reflect_relationship` 触发, 后者已被"有新观察才反思"门控。

## 当前状态

- **核心机制已落地**：反思去重、观察去重、遗忘降权、LLM 反应决策、LLM 信任度、
  LLM 冲突失效、持久化、夜间固化 (episode)、身份层信念。
- **游戏世界层已落地**：多 NPC 空间共存、空间感知、距离调度档位、世界事件、
  模拟/自治双循环、动作效果钩子、行为链事件、结构化视觉事件、独立持久化。
- **NPC↔NPC 社交层 + 谣言已落地** (NextPlan P1)：per-entity 面、社交感知、
  传闻按跳数折扣、内生事件；相关开关缺省关闭。
- **记忆固化 + 身份信念已落地** (NextPlan P2)：episode 吸收旧观察、冲突扫描
  从二次降为线性、跨玩家身份信念可注入决策。
- **评测与可视化**：三组消融实验的结果已回填 [`evals/README.md`](evals/README.md)；
  Phaser 回放器 M0–M5 已实现并 E2E 验证（含真实旧格式回放与直播跟随）。
- **信任度不随遗忘淡化是显式设计**：信任是持久的关系认知, `judge_trust` 只看
  关系记忆内容、刻意不看 importance (帮过的人不会因久远被时间冲淡)。回归测试
  `test_trust_does_not_fade_with_forgetting` 锁定该行为。
- **距离调度已落地**：blog「问题一」的"距离/注意力 → 档位"自动调度由世界层
  `tier_of`/`schedule_tiers` 实现 (近处 full、远处 compressed/idle), 不再手动
  `set_tier`。

后续可扩展（见 [NextPlan.md](NextPlan.md)）：**P3 关系阶段 + 修复 + 称呼**、
**P4 idle 低成本自治**；以及 [AutoSimPlan.md](AutoSimPlan.md) 的阶段 3（涌现：
NPC 互相求助、结盟对抗）、多玩家对抗、更多区域与 NPC。
