# LongMemEval 记忆召回评测

状态：已实现并完成离线与 oracle smoke 验证（2026-11-01）。关联：[评测模块](evaluation.md)、[记忆模块](memory.md)、[分层记忆](tiered-memory.md)。

## 目标与边界

用 LongMemEval 评估当前记忆层的**检索召回**，而不是改造成新的对话任务。评测作为仓库外的独立模块 `evals/longmemeval/` 接入：

- 不修改 `game_agent` 的公开 API、记忆语义、NPC、规划或对话；
- 只通过 `MemoryStore` / `MemoryRecord` 公开接口写入与检索；
- 数据集、适配器、指标、CLI 全部在 `evals/longmemeval/` 内；
- 默认离线可跑小 fixture；真实数据集由调用方显式下载，不入库。

首版只做检索指标。LongMemEval 的 QA 回答与 LLM 裁判另立模块，不混入召回口径。

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

- Python 离线全集 **591 项通过、6 项真实端点测试跳过**；LongMemEval 专项 7 项，覆盖 fixture、日期、turn/session 指标、后端映射、CLI 和 stratified 采样。
- fixture smoke：2 题，HashEmbedder，产物 `summary.json` / `per_question.jsonl` 正常。
- oracle smoke：`--limit 6 --sample stratified`，覆盖 6 个 question_type；HashEmbedder 与 RealEmbedder 均完成，RealEmbedder 结果仅用于流程验证。
- oracle 只含证据会话，session recall 在 oracle 上接近 1 是数据口径，不代表带干扰项的真实召回；完整 S/M 未在本次运行（数据不入库，按需下载）。
- 未实现 QA 回答/LLM 裁判，未修改核心记忆检索公式。
