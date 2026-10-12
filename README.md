# persona_agent — 千人千面游戏 NPC 框架

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
| Reflection | `reflection.py` | 分**自我反思**与**关系反思**两条轨; 带证据引用 + 冲突失效/衰减 |
| Planning | `planning.py` | 层次化 (日→小时→分钟); plan 作为记忆参与检索; 反应后从当前时刻重规划 |
| Reacting | `reacting.py` | 效用函数 `U=w_s·V_s+w_g·V_g−C_int`, 事件价值与关系信任度均由 LLM 判断 (签名缓存), 人格权重 + 信任调制 |
| Dialogue | `dialogue.py` | 非全知: 只用自己记忆流, 检索时把"对话者是谁"并入查询 |
| 成本闸门 (blog 问题一) | `npc.py` | 分级认知 (full/compressed/idle) + 语义缓存 |

## LLM / 向量层

- `llm.LLMClient`: 抽象接口, 八个方法 `complete / score_importance /
  reflection_questions / reflection_insights / generate_plan / decompose_activity /
  score_event / judge_trust`。实现者只应使用传入的记忆内容 (非全知原则)。
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
   余弦比对, `>= 0.95` 视为同一条认知的复述, 跳过不入库。阈值来自
   gte-Qwen2 实测: 措辞不同的重复 0.955~1.000, 不同面向的独立洞察 <= ~0.90。

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

## 五个探针 (集成测试)

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

## 遗忘 / 衰减

记忆不是只增不减的。`memory.py` 的 `decay_and_forget` 按时间衰减并遗忘:

```
强度 = base × 0.5 ** (age / half_life)
base  = 反思的 confidence / 观察与计划的 importance÷10
age   = now − max(timestamp, last_accessed)   # 被回忆过 → 衰减更慢
跌破 FORGET_FLOOR(0.15) → 失效 (valid=0)
```

- **分层半衰期**: 原始观察 ~2 天最先淡去, 反思(高阶认知) ~2 周留存最久,
  计划隔夜即过期。
- **保护**: 被有效反思引用为证据的观察不遗忘 —— 已固化为高阶认知, 忘了会断
  证据链。保护集在每次清扫前按当前有效反思快照计算。
- **回忆强化**: `last_accessed` 被检索时刷新, 近期被用到的记忆衰减更慢。
- **触发**: NPC 游戏时钟每推进 6h 自动清扫 (纯本地计算, 零 LLM 成本), 也可
  `npc.forget(now)` 手动触发。
- **副作用**: 信任度由有效观察派生, 久远的帮助/背叛淡去后, 信任自然向 0 回归
  —— 关系需要持续维护, 这符合直觉。

`python examples/forgetting.py` 演示 ~8 天时间跳跃后的分层遗忘。

## 观察去重 (事件重放不灌水)

`npc.observe()` 入库前, 用 embedder 与**同玩家**近期观察做语义比对
(`OBS_DEDUP_THRESHOLD = 0.92`, 比反思去重的 0.95 略松, 观察更公式化、
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
  `npc.react` 的语义决策缓存, 反应路径的 LLM 开销可控。
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

> 注: `reflection.check_conflicts` 的冲突失效仍用词表 (它判的是"信任类反思 vs
> 背叛类观察"的矛盾, 与信任度打分是两回事, 暂未纳入 LLM)。

## 当前局限 (与 blog 一致, 待办)

- 反思去重、观察去重、冲突失效、遗忘/衰减、LLM 反应决策、LLM 信任度均已落地。
- 成本闸门是"档位+缓存"的粗粒度方案, `set_tier` 靠调用方手动设,
  未做"距离/注意力 → 档位"的自动调度。
- 遗忘是"整条失效", 未做部分衰减 (如把低强度记忆的 importance 逐步调低而非直接删除)。
- 冲突失效 (`check_conflicts`) 仍是词表, 未纳入 LLM 判断。
