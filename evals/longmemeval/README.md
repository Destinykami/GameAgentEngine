# LongMemEval 记忆召回评测

独立评测模块：把 LongMemEval 的 history turn 逐条写入一个临时 `MemoryStore`，再按问题检索，计算官方 turn/session 召回指标。不会修改核心记忆、NPC 或对话语义。

设计与边界见 [`docs/modules/longmemeval.md`](../../docs/modules/longmemeval.md)。

## 数据

使用清理版 `xiaowu0162/longmemeval-cleaned`（MIT），完整数据不入库：

```bash
python -m evals.longmemeval.download --split oracle   # ~15 MB
python -m evals.longmemeval.download --split s        # ~277 MB
python -m evals.longmemeval.download --split m        # ~2.7 GB
```

默认下载到 `evals/longmemeval/data/`（已 gitignore）。仓库只保留 `fixtures/sample.json` 两道题的离线 fixture。

## 运行

```bash
# 内置 fixture，离线
python -m evals.longmemeval --limit 2 --top-k 50

# oracle smoke（hash 嵌入）
python -m evals.longmemeval --data evals/longmemeval/data/longmemeval_oracle.json \
    --limit 6 --top-k 50 --embedder hash --sample stratified

# 真实语义嵌入（端点可用时）
python -m evals.longmemeval --data evals/longmemeval/data/longmemeval_oracle.json \
    --limit 20 --top-k 50 --embedder real --sample stratified
```

输出到 `data/eval/longmemeval/<时间戳>/summary.json` 与 `per_question.jsonl`。

## 指标

- turn 级 `recall_all@k`、`recall_any@k`、`ndcg_any@k`
- session 级 `recall_all@k`、`recall_any@k`、`ndcg_any@k`
- 默认 `k=5,10,50`；按 `question_type` 分组

字段口径对齐官方 `src/retrieval/eval_utils.py`。hash 嵌入只验证流程，不代表真实语义召回质量。

## 排序消融

`--retrieval memory|relevance|session` 只改变评测侧重排，不修改核心检索：

```bash
python -m evals.longmemeval --data evals/longmemeval/data/longmemeval_s_cleaned.json     --limit 20 --top-k 50 --embedder real --sample stratified --retrieval relevance
```

S20 结果：relevance-only 明显优于现有 memory 排序（session recall_all@10 0.400 → 0.900），session 聚合没有超过 relevance。详见设计文档。`oracle` 只含证据会话，session recall 接近 1 不代表带干扰项的真实效果；完整 S/M 需下载后显式运行。
