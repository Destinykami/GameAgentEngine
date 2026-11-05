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

输出到 `data/eval/longmemeval/<时间戳>/summary.json` 与 `per_question.jsonl`；长跑加 `--resume` 跳过已完成题目。

## 指标

- turn 级 `recall_all@k`、`recall_any@k`、`ndcg_any@k`
- session 级 `recall_all@k`、`recall_any@k`、`ndcg_any@k`
- 默认 `k=5,10,50`；按 `question_type` 分组

字段口径对齐官方 `src/retrieval/eval_utils.py`。hash 嵌入只验证流程，不代表真实语义召回质量。

## 原文混合检索对照（2026-11-06）

新增三组共享同一原文片段和生产 `MemoryStore.hybrid_retrieve` 的模式：`bm25`、`dense`、`hybrid`。前三种历史模式 `memory/relevance/session` 保留；新三组之间可比较融合差异，新旧组还存在原文切块和候选组织差异，不能将其差值只归因为 RRF。

```bash
python -m evals.longmemeval --retrieval bm25 --limit 2 --top-k 5 --out /tmp/lme-bm25
python -m evals.longmemeval --retrieval dense --limit 2 --top-k 5 --out /tmp/lme-dense
python -m evals.longmemeval --retrieval hybrid --limit 2 --top-k 5 --out /tmp/lme-hybrid
```

三组均按 turn 写原文、以来源 ID 映射回 turn；dense/hybrid 在查询前显式补齐本题可见片段向量。索引失败、覆盖不全或查询降级直接报错，不作为成功结果。BM25 不需要 embedding。top-k 范围为 5–128；各组使用独立输出目录，resume 不允许混用模式或 top-k。

`per_question.jsonl` 追加 retrieval_diagnostics，包含各路候选数、完整性、实际命中的片段/偏移和排名、冷索引时间、查询时间与整题管线时间。summary 汇总降级数、编码片段数和耗时；这些不是并发服务 P95 或 HTTP 调用次数。指标单位仍为 turn/session，旧 QA reader 会展开选中的完整 turn，与 NPC 的片段及 3000 字符上下文不同；本轮未运行 QA。

2026-11-06 离线 fixture：三组各 2 题，HashEmbedder，全部完成且无降级，turn/session recall_all@5 均为 1.0。产物位于 `data/eval/longmemeval/hybrid-fixture-1d_tzfg9/`，含逐题结果、summary、日志和 comparison.json。小样本与词袋哈希只证明流程，不是新 S500 分数或真实语义效果。

## 历史排序消融

`--retrieval memory|relevance|session` 只改变评测侧重排，不修改核心检索：

```bash
python -m evals.longmemeval --data evals/longmemeval/data/longmemeval_s_cleaned.json     --limit 20 --top-k 50 --embedder real --sample stratified --retrieval relevance
```

S500 完整结果：核心 relevance 权重将 session recall_all@10 从 0.350 提升到 0.892，turn recall_all@5 从 0.128 提升到 0.510；S500 QA accuracy 0.676 vs memory 0.342（reader/judge 同端点，存在自评偏差）。详见设计文档。`oracle` 只含证据会话，session recall 接近 1 不代表带干扰项的真实效果；完整 S/M 需下载后显式运行。


## Reader + LLM judge

```bash
# 复用已有召回结果，跑 S20 QA
python -m evals.longmemeval --data evals/longmemeval/data/longmemeval_s_cleaned.json \
    --limit 20 --sample stratified \
    --qa-results data/eval/longmemeval/s20-relevance/per_question.jsonl \
    --qa-turns 50 --out data/eval/longmemeval/s20-qa
```

输出 `qa.jsonl` 与 `qa_summary.json`；`--qa-resume` 跳过已完成题目。reader 和 judge 使用同一端点时存在自评偏差，结果不等同于官方 GPT-4o 裁判分数。
