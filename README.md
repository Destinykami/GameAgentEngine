# persona_agent — 千人千面游戏 NPC 框架

> 先看 **[OVERVIEW.md](OVERVIEW.md)** 的系统总览 (自我/面解耦、LLM 推理栈、
> 记忆卫生链、判断型决策、成本管理、验证体系)。本 README 是逐模块的实现细节。

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
| Memory Stream + Retrieval | `memory.py` | 每条记忆带 `player_id`; 检索三维评分 (recency/importance/relevance) 之外, 对当前玩家记忆加权 |
| Reflection | `reflection.py` | 分**自我反思**与**关系反思**两条轨; 带证据引用 + LLM 矛盾强度冲突失效/衰减 |
| Planning | `planning.py` | 层次化 (日→小时→分钟); plan 作为记忆参与检索; 反应后从当前时刻重规划 |
| Reacting | `reacting.py` | 效用函数 `U=w_s·V_s+w_g·V_g−C_int`, 事件价值与关系信任度均由 LLM 判断 (签名缓存), 人格权重 + 信任调制 |
| Dialogue | `dialogue.py` | 非全知: 只用自己记忆流, 检索时把"对话者是谁"并入查询 |
| 成本闸门 (blog 问题一) | `npc.py` | 分级认知 (full/compressed/idle) + 决策缓存 |
| **游戏世界层** | `world.py` | 多 NPC + 多玩家空间共存、空间感知、**距离自动调度档位**、世界事件、模拟驱动、独立持久化 (blog 问题一落地) |

## LLM / 向量层

- `llm.LLMClient`: 抽象接口, 九个方法 `complete / score_importance /
  reflection_questions / reflection_insights / generate_plan / decompose_activity /
  score_event / judge_trust / judge_conflict`。实现者只应使用传入的记忆内容 (非全知原则)。
- `llm_real.RealLLM`: 唯一实现, 通过 OpenAI 兼容接口 (`/v1/chat/completions`)
  接入 SGLang 部署的 `Qwen3.8-27B-Coder/BF16`。要换别的 OpenAI 兼容端点,
  改 `base_url` / `model` 即可。
- `embeddings.Embedder`: 可插拔向量接口, 两个实现:
  - `HashEmbedder` (默认回退): 词袋哈希, 余弦相似度反映**词面重叠**, 确定性、
    零依赖。中文按单字、英文按词分词。
  - `embeddings_real.RealEmbedder`: 接 OpenAI 兼容 `/v1/embeddings`, 默认指向
    SGLang 部署的 `Alibaba-NLP/gte-Qwen2-1.5B-instruct` @ `10.121.39.10:30006`
    (1536 维, 语义相似度 —— 换说法的同义句也能高相似)。
  - `make_embedder()`: 优先真实端点, 不可达自动回退 HashEmbedder。示例默认用它。

## 运行

无第三方运行时依赖 (纯标准库)。需要 LLM 端点可达 (默认 10.121.39.10:30005)。

```bash
# 端到端 demo: 真实语言模型驱动同一个 Klaus 对 Aria 与 Bram 的千人千面
python examples/demo_real.py

# 集成探针 (需 pytest, 需 LLM 可达; 不可达自动 skip)
pytest tests/ -v
```

## 反思质量 (级联切断 + 语义去重)

两个曾导致"57 条记忆里 51 条反思"失控的机制, 已修:

1. **级联切断**: 反思找证据时限定 `types=["observation"]` —— 反思只能由真实
   观察支撑, 不能拿别的反思当证据 (否则一代代复述放大自己)。
2. **语义去重**: `ReflectionEngine._save` 保存前, 新洞察与同玩家已有反思做
   余弦比对, `>= 0.92` 视为同一条认知的复述, 跳过不入库。阈值来自
   gte-Qwen2 实测: 措辞不同的重复稳定落 0.85~0.94, 不同面向的独立洞察
   多 <= ~0.90; E6 从 0.95 下调到 0.92 (0.95 在真实数据几乎不生效)。

效果: 2 条观察 → 4 条互不重复的反思 (两两相似度最高 0.92), 证据全指向观察。
用 `python tools/inspect_npc.py data/<name>.db` 可审查证据链与相似度。

## 接入 LLM (RealLLM)

`persona_agent/llm_real.py` 的 `RealLLM` 通过 OpenAI 兼容接口接入
SGLang 部署的 `Qwen3.8-27B-Coder/BF16`:

```python
from persona_agent import NPC, RealLLM, HashEmbedder
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
from persona_agent import NPC, RealLLM, make_embedder

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

在单个 NPC 之上加了一层**世界层** (`world.py`)，把"脚本手喂单个 NPC"升级为
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
- **模拟驱动**：`World.step(now)` 完整循环——时钟→距离调度→空间感知→按档自我
  反思→遗忘清扫→自动落库。
- **独立持久化**：世界状态单独存 `world.db`（实体位置+时钟+NPC 注册表），与每
  NPC 的独立 `<name>.db` 分离，不破坏"一 NPC 一库"。`World.load(llm, embedder)`
  跨进程恢复整个世界（含各 NPC 记忆流与面）。

```python
from persona_agent import World, Location, RealLLM, make_embedder
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

## 六个探针 (集成测试)

`probes.py` 把"它真的千人千面了吗"变成对真实 LLM 的集成回归。每个探针混合
**确定性架构断言** (信任度差异、特质稳定, 不依赖 LLM 措辞) 与 **宽松真实 LLM
断言** (对话不同、非全知不编造、计划目标导向, 对措辞鲁棒)。需 LLM 可达,
不可达时 `pytest` 自动 skip。

1. **一致性探针** — 对两个玩家信任度不同, 且同一问话回答不同。
2. **非全知探针** — 没观察过的玩家, 不应自信编造其背叛。判定用 **LLM 裁判**
   (`RealLLM.ask`) 而非关键词: 中文否定式 (没偷过/偷没偷/没什么印象/没留意过)
   关键词判不了, 交给 LLM 判"是否自信断言具体事实"。
3. **持久性探针** — 被背叛后, 对背叛者的信任仍低于对帮助者 (相对断言)。
4. **漂移探针** — 人格特质随时间稳定, 生成的计划仍由 persona 驱动。
5. **第一人称探针** — 记忆流是第三人称叙述, NPC 开口时不该用自己的名字称呼
   自己 (防"梳理和 Isabella 的协作流程"式自指 bug)。对话 prompt 里显式把
   记忆中的 NPC 名字映射为"我"。
6. **世界隔离探针** — 同一玩家对不同 NPC 的面独立: 帮过的 NPC 信任为正、骗过的
   为负, 且该 NPC 的记忆流不含另一个 NPC 的交互 (跨 NPC 不污染)。验证世界层的
   多 NPC 千人千面。

## 遗忘 / 衰减 (部分衰减降权, 不删除)

记忆不是只增不减的, 但也不会被抹掉。`memory.py` 的 `decay_and_forget` 按时间
**下调 importance** (降权), 渐近到 `MIN_IMPORTANCE`(1.5) 为止 —— 记忆**保留**
(valid 恒 1), 只是检索权重降低, 老记忆自然跌出前排, 被回忆又能升回:

```
importance *= 0.5 ** (age / half_life)      # 渐近降到 MIN_IMPORTANCE, 不删除
age   = now − max(timestamp, last_accessed)  # 被回忆过 → 衰减更慢
```

- **分层半衰期**: 原始观察 ~2 天最先降权, 反思(高阶认知) ~2 周降权最慢,
  计划隔夜即降权。
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

`npc.observe()` 入库前, 用 embedder 与**同玩家**近期观察做语义比对
(`OBS_DEDUP_THRESHOLD = 0.92`, 与反思去重同阈值, 观察更公式化、
近义重复更多)。近义则**合并**而非跳过:

- 不新增记录, 返回已有观察的 id (反思证据引用不断)。
- 刷新 `last_accessed` —— 事件反复发生 = 记忆强化, 衰减锚点后移, 抗遗忘。
- importance +1 (上限 10) —— 反复发生的事件更突出。

效果: 事件重放不再灌水 —— 信任度不被重复计分, 重要性累积不被反复抬高,
检索 top_k 不被重复记忆占满。限定同玩家流: 跨玩家的相似文本是不同关系,
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

## 当前状态 (与 blog 一致)

- 反思去重、观察去重、遗忘降权、LLM 反应决策、LLM 信任度、LLM 冲突失效、持久化、
  **游戏世界层** (多 NPC 空间共存、空间感知、距离调度档位、世界事件、模拟驱动、
  独立持久化) 均已落地。
- 信任度**不随遗忘淡化是显式设计**: 信任是持久的关系认知, `judge_trust` 只看
  关系记忆内容、刻意不看 importance (帮过的人不会因久远被时间冲淡)。回归测试
  `test_trust_does_not_fade_with_forgetting` 锁定该行为。
- **距离调度已落地**: blog「问题一」的"距离/注意力 → 档位"自动调度由世界层
  `tier_of`/`schedule_tiers` 实现 (近处 full、远处 compressed/idle), 不再手动
  `set_tier`, 无遗留债。

后续可扩展: 更多区域与 NPC、玩家脚本动作 (帮/骗/搜捕) 驱动关系事件、多玩家对抗。
