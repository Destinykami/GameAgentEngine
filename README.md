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
| Reacting | `reacting.py` | 效用函数 `U=w_s·V_s+w_g·V_g−C_int`, 人格权重 + 关系信任度调制 |
| Dialogue | `dialogue.py` | 非全知: 只用自己记忆流, 检索时把"对话者是谁"并入查询 |
| 成本闸门 (blog 问题一) | `npc.py` | 分级认知 (full/compressed/idle) + 语义缓存 |

## LLM / 向量层

- `llm.LLMClient`: 抽象接口, 六个方法 `complete / score_importance /
  reflection_questions / reflection_insights / generate_plan / decompose_activity`。
  实现者只应使用传入的记忆内容 (非全知原则)。
- `llm_real.RealLLM`: 唯一实现, 通过 OpenAI 兼容接口 (`/v1/chat/completions`)
  接入 SGLang 部署的 `Qwen3.8-27B-Coder/BF16`。要换别的 OpenAI 兼容端点,
  改 `base_url` / `model` 即可。
- `embeddings.Embedder`: `HashEmbedder` 用词袋哈希向量, 余弦相似度反映词面重叠,
  支撑检索的相关性维度。接真实 embedding 时实现 `embed()` 并保证归一化即可。

## 运行

无第三方运行时依赖 (纯标准库)。需要 LLM 端点可达 (默认 10.121.39.10:30005)。

```bash
# 端到端 demo: 真实语言模型驱动同一个 Klaus 对 Aria 与 Bram 的千人千面
python examples/demo_real.py

# 集成探针 (需 pytest, 需 LLM 可达; 不可达自动 skip)
pytest tests/ -v
```

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

## 四个探针 (集成测试)

`probes.py` 把"它真的千人千面了吗"变成对真实 LLM 的集成回归。每个探针混合
**确定性架构断言** (信任度差异、特质稳定, 不依赖 LLM 措辞) 与 **宽松真实 LLM
断言** (对话不同、非全知不编造、计划目标导向, 对措辞鲁棒)。需 LLM 可达,
不可达时 `pytest` 自动 skip。

1. **一致性探针** — 对两个玩家信任度不同, 且同一问话回答不同。
2. **非全知探针** — 没观察过的玩家, 不应编造其背叛细节。
3. **持久性探针** — 被背叛后, 信任度在长时间后仍为负。
4. **漂移探针** — 人格特质随时间稳定, 生成的计划仍由 persona 驱动。

## 当前局限 (与 blog 一致, 待办)

- 记忆只增不合并: 缺记忆固化/去重/遗忘 (blog 2.2.5 的 `R=(content,evidence,confidence,timestamp)` 已部分落地, 冲突失效已实现, 去重未做)。
- 反应决策是关键词价值表, 非学习型决策函数。
- 成本闸门是"档位+缓存"的粗粒度方案, 未做按距离的动态调度。
- 检索相关性用词袋哈希向量; 接真实 embedding 后, 非全知与检索质量会进一步提升。
