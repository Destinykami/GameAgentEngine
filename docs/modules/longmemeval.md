# LongMemEval 记忆召回评测

状态：已实现并完成离线与 oracle smoke 验证（2026-11-01）。关联：[评测模块](evaluation.md)、[记忆模块](memory.md)、[分层记忆](tiered-memory.md)。

## 目标与边界

用 LongMemEval 评估当前记忆层的**检索召回**，而不是改造成新的对话任务。评测作为仓库外的独立模块 `evals/longmemeval/` 接入：

- 不修改 `game_agent` 的公开 API、记忆语义、NPC、规划或对话；
- 只通过 `MemoryStore` / `MemoryRecord` 公开接口写入与检索；
- 数据集、适配器、指标、CLI 全部在 `evals/longmemeval/` 内；
- 默认离线可跑小 fixture；真实数据集由调用方显式下载，不入库。

首版只做检索指标。LongMemEval 的 QA 回答与 LLM 裁判另立模块，不混入召回口径。

## 检索排序消融

为了判断低 turn recall 是数据问题还是当前 recency/importance/relevance 等权排序的问题，评测后端提供 `--retrieval` 三种模式，全部只发生在 `evals/longmemeval/`：

- `memory`：直接使用 `MemoryStore.retrieve` 的现有排序（基线）；
- `relevance`：调用核心 `MemoryStore.retrieve(weights=(0, 0, 1))`，只按 relevance 排序；
- `session`：评测侧按 session 聚合最大 relevance，先排 session，再排 session 内 turn，最后截 top-k；用于观察 session 级召回上限。

三种模式共享同一批 turn、同一批预编码向量和同一 `MemoryStore` 写入，只改变候选排序，不修改核心检索公式。S20 上对比 `memory`、`relevance`、`session`，并保留 `--retrieval` 参数和 per-question 审计。

## 数据来源

使用官方清理版 `xiaowu0162/longmemeval-cleaned`（MIT），不使用已弃用的原始 `longmemeval`：

| 文件 | 用途 | 大小 |
|---|---|---|
| `longmemeval_oracle.json` | 只含证据会话，适合流程 smoke | ~15 MB |
| `longmemeval_s_cleaned.json` | 完整 S split，约 115k token 历史 | ~277 MB |
| `longmemeval_m_cleaned.json` | 完整 M split | ~2.7 GB |

仓库只提交一个手写小 fixture（2 个问题）用于测试；完整数据放 `evals/longmemeval/data/`，由 `.gitignore` 排除。下载脚本显式调用 HuggingFace，不隐式联网。

字段：

- `question_id`、`question_type`、`question`、`answer`、`question_date`
- `haystack_session_ids`、`haystack_dates`、`haystack_sessions`
- `answer_session_ids`
- 每个 turn 为 `{role, content, has_answer?}`；`has_answer` 是 turn 级证据标签。

## 模块布局

```text
evals/longmemeval/
├── __init__.py
├── __main__.py          # python -m evals.longmemeval
├── cli.py               # 参数、运行、产物
├── dataset.py           # 数据模型、日期解析、加载/校验
├── backend.py           # MemoryBackend 协议 + GameAgentMemoryBackend
├── metrics.py           # 官方 recall_all / ndcg_any 口径
├── runner.py            # 单题/批量评测与聚合
├── download.py          # 显式下载 cleaned split
├── README.md
└── fixtures/sample.json
```

依赖方向：`evals.longmemeval → game_agent.memory / game_agent.models`，核心不反向依赖评测。后端可以替换成别的记忆系统，只要实现 `MemoryBackend`。

## 召回契约

`dataset.py` 提供不可变数据模型：

```python
@dataclass(frozen=True)
class Turn:
    role: str
    content: str
    has_answer: bool

@dataclass(frozen=True)
class Session:
    session_id: str
    at: float          # 小时；由 haystack_dates 解析
    turns: tuple[Turn, ...]

@dataclass(frozen=True)
class Question:
    question_id: str
    question_type: str
    question: str
    answer: str
    at: float
    sessions: tuple[Session, ...]
    answer_session_ids: frozenset[str]
```

`MemoryBackend`：

```python
class MemoryBackend(Protocol):
    def retrieve(self, question: Question, top_k: int) -> tuple[RetrievedTurn, ...]: ...
```

默认实现 `GameAgentMemoryBackend`：

1. 每题新建一个内存 `MemoryStore`，确保问题之间不串记忆。
2. 每个 turn 写一条 `MemoryRecord(type="observation", importance=5.0, player_id=None, timestamp=session.at)`；内容保留 `[role] content`。
3. 记录 `memory_id -> (session_id, turn_index, Turn)`。
4. 用 `store.retrieve(question, now=question.at, top_k=top_k, mark_accessed=False, min_relevance=0.0)` 检索。
5. 返回按 `score` 排序的 `RetrievedTurn`；未映射的 id 跳过。
6. 每题结束关闭 store。

**不经过 `NPC.observe`**：避免观察去重、重要性打分、反思阈值、关系流过滤污染召回口径。LongMemEval 的 turn 是原文证据，必须逐条保留。

S split 每题约 400–600 个 turn（约 49 万字符），逐 turn 请求真实嵌入不可行；且存在 76k 字符的超长 filler turn，直接整批请求会触发 embedding 端点 400。后端在写入前对全部 turn 文本做**批量预编码**，用 `CachedBatchEmbedder` 包住原 embedder：

- 每段文本截断到 6000 字符再编码，`MemoryStore` 仍保存完整原文；
- 按累计 8000 字符、最多 16 段分组，避免超长 batch；
- 端点仍返回 400 时递归二分 batch，单段仍失败才抛出；
- 缓存截断文本到向量，`MemoryStore.add` 的逐条调用命中缓存；查询文本走 fallback。

该优化只存在于评测适配器，不改核心写入逻辑。

日期解析支持 `%Y/%m/%d (%a) %H:%M` 等常见格式，统一转成 UTC 小时；解析失败按题目 id 报错，不静默猜测。时间用于 `MemoryStore` 的 recency 分，不改变检索公式。

## 指标

严格采用官方 `src/retrieval/eval_utils.py` 的二值口径：

- `recall_all@k`：所有证据文档都进 top-k；
- `ndcg_any@k`：按二值相关性计算 NDCG@k；
- turn 级：证据 = `has_answer=True` 的 turn；
- session 级：把 turn 结果按首次出现的 session 去重后再算，证据 = `answer_session_ids`；
- 报告 turn/session 的 `k=5,10,50`；turn 级额外 report `recall_any` 便于观察部分命中。

聚合：

- 总体均值；
- 按 `question_type` 分组均值与题数；
- 每题保留 `retrieved_turns`（session/turn/得分/文本截断）与指标，便于审计。

## CLI 与产物

```bash
# 小 fixture，离线
python -m evals.longmemeval --limit 2 --top-k 50

# 下载 oracle 后 smoke
python -m evals.longmemeval.download --split oracle
python -m evals.longmemeval --data evals/longmemeval/data/longmemeval_oracle.json \
    --limit 6 --top-k 50 --embedder hash --sample stratified
```

参数：`--data`、`--limit`、`--top-k`、`--embedder hash|real`、`--question-type`、`--sample first|stratified`、`--out`。`--sample stratified` 按 question_type 轮转，适合小规模 smoke；完整评测用 `--limit 0`。

产物：`data/eval/longmemeval/<时间戳>/summary.json` 与 `per_question.jsonl`；不把结果写回仓库文档，除非单独确认结果结论。

长跑检查点：CLI 每完成一题就追加写入 `per_question.jsonl`（flush），全部结束后再写 `summary.json`。传 `--resume` 时读取已有行、按 `question_id` 跳过已完成题目，只跑剩余题并在结束时用已有 + 新结果重算 summary。这样 500 题中途失败后可用同一 `--out` 继续，不丢前序结果。S500 正在按此方式运行。

## 验收

- fixture 加载、日期解析、切分与字段校验；
- 已知排序上的 `recall_all` / `ndcg_any` 数值测试；
- `GameAgentMemoryBackend` 的 turn→session 映射与 top-k 顺序测试；
- CLI 离线 smoke 产出 summary/per-question；
- 完整离线测试不联网；真实数据集下载与真实嵌入/模型运行显式触发；
- 不改核心源码；`git diff --check` 通过。

## 非目标

- 不做 LongMemEval QA 回答或 LLM 裁判；
- 不把完整 S/M 数据提交到仓库；
- 不修改 `MemoryStore` 的检索公式、去重、反思或 NPC 语义；
- 不宣称 hash 嵌入的召回结果代表真实语义检索质量。

## 实施与验证

实现位于 `evals/longmemeval/`：`dataset.py`、`backend.py`、`metrics.py`、`runner.py`、`cli.py`、`download.py`、`fixtures/sample.json`；没有修改 `src/`。`MemoryBackend` 协议允许替换检索实现，默认 `GameAgentMemoryBackend` 只使用 `MemoryStore.add/retrieve`。

2026-11-01 验证：

- Python 离线全集 **600 项通过、6 项真实端点测试跳过**；LongMemEval 专项 11 项，覆盖 fixture、日期、turn/session 指标、后端映射、CLI、stratified 采样、排序模式与 `--resume`。
- fixture smoke：2 题，HashEmbedder，产物 `summary.json` / `per_question.jsonl` 正常。
- oracle smoke：`--limit 6 --sample stratified`，覆盖 6 个 question_type；HashEmbedder 与 RealEmbedder 均完成，RealEmbedder 结果仅用于流程验证。
- oracle 只含证据会话，session recall 在 oracle 上接近 1 是数据口径，不代表带干扰项的真实召回；完整 S/M 未在本次运行（数据不入库，按需下载）。
- **LongMemEval-S 20 题分层样本**（`--limit 20 --sample stratified --embedder real --top-k 50`）：20 题全部完成，覆盖 6 个 question_type。结果：

| 层级 | recall_all@5 | recall_all@10 | recall_all@50 | recall_any@5 | recall_any@10 | recall_any@50 | ndcg_any@5 | ndcg_any@10 | ndcg_any@50 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| turn | 0.050 | 0.050 | 0.350 | 0.400 | 0.400 | 0.750 | 0.203 | 0.208 | 0.288 |
| session | 0.400 | 0.400 | 0.400 | 0.650 | 0.750 | 0.750 | 0.438 | 0.455 | 0.460 |

这是当前记忆层的**20 题基线样本**，不是完整 500 题分数，也不含 QA 回答评分。turn recall_all 偏低说明当前 recency/importance/relevance 等权排序对 LongMemEval 的长历史证据不理想；session recall 明显高于 turn recall，说明会话级定位比精确证据 turn 容易。

### S20 排序消融

同一批 20 题、同一 RealEmbedder、同一 top-k=50，只改评测侧重排：

| 模式 | turn recall_all@5 | turn recall_all@10 | turn recall_all@50 | session recall_all@5 | session recall_all@10 | session recall_all@50 | session ndcg@5 | session ndcg@10 | session ndcg@50 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| memory（现有排序） | 0.050 | 0.050 | 0.350 | 0.400 | 0.400 | 0.400 | 0.438 | 0.455 | 0.460 |
| relevance（核心 `weights=(0,0,1)`） | **0.350** | **0.500** | **0.750** | **0.650** | **0.950** | **0.950** | **0.757** | **0.826** | **0.830** |
| session（session 聚合） | 0.150 | 0.200 | 0.650 | 0.600 | 0.650 | 0.650 | 0.732 | 0.751 | 0.751 |

结论：

- relevance-only 显著优于现有等权排序：turn recall_all@5 从 0.050 到 0.350，session recall_all@10 从 0.400 到 0.950。
- 这说明问题主要来自 recency/importance 等权，而不是评测指标；relevance 模式已经走核心 `MemoryStore.retrieve(weights=(0,0,1))`，不是评测侧伪重排。
- session 聚合没有超过 relevance；它把 top turn 预算集中到少数 session，session@10 降到 0.650。当前样本下不需要先聚合 session。
- 按题型，relevance 下 knowledge-update / single-session-preference 的 session recall_all@5 达到 1.000；single-session-assistant 0.667、single-session-user 0.667、temporal-reasoning 0.333、multi-session 0.250；multi-session session@10 为 0.750，temporal @10 为 1.000，仍是最主要短板。
- 这些是 S20 分层样本结果；默认核心权重未改，是否切换默认需要完整 500 题和近期事件回归后再定。

- 未实现 QA 回答/LLM 裁判，未修改核心记忆检索公式。
