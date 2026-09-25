# RAG-verify

**RAG 质量评测与对比工具** —— 在同一套考卷上比出多个 RAG 系统谁更好，并且能解释**差在哪一环**。

不是给一个总分，而是输出：检索层 / 上下文层 / 生成层 / 引用层 / 系统层分层指标 + 六类错误归因 + Pareto 权衡图。
评测工具**不侵入**被测系统，只认一份「答题卡」格式的 JSONL，谁用什么框架都能横向比。

```
[参赛方 RAG] --run_log.jsonl--> [rag-eval] --results.json--> [对比报告]
                                    ^
                    dataset.jsonl + prompts/ + LLM Judge
```

---

## 快速开始

### 一、主办方：跑一场对比评测

```bash
pip install -r requirements.txt          # 只有 jsonschema；跑 LLM Judge 时用标准库直连，无额外依赖

# 1. 跑通全链路（先用自带 baseline 试）
python corpus/baseline.py --dataset dataset/dataset_v1.jsonl --out logs/baseline.jsonl
python -m rag_eval.cli validate --dataset dataset/dataset_v1.jsonl --run-log logs/baseline.jsonl
python -m rag_eval.cli run      --dataset dataset/dataset_v1.jsonl --run-log logs/baseline.jsonl

# 2. 多系统对比（答卷放一起跑）
python -m rag_eval.cli run --dataset dataset/dataset_v1.jsonl \
    --run-log logs/team-A.jsonl --run-log logs/team-B.jsonl \
    --out results/all.json
```

### 二、发卷给参赛方

```bash
python -m rag_eval.cli make-public --dataset dataset/dataset_v1.jsonl
python -m rag_eval.cli pack        --dataset dataset/dataset_v1.jsonl
# -> 把 dist/rag-bench-kit.zip 发出去，收回 run_log.jsonl
```

工具箱自带 README、公开考卷、官方 chunk 库、接入模板、校验器，参赛方解压即可用。

### 三、参赛方：3 步交卷

```bash
pip install -r requirements.txt
# 1. 改 templates/adapter_template.py，实现 ask(question)
# 2. 跑题
python templates/adapter_template.py --dataset dataset/dataset_public.jsonl --out run_log.jsonl --limit 5
# 3. 自查，0 个错误才能交
python -m rag_eval.cli validate --dataset dataset/dataset_public.jsonl --run-log run_log.jsonl
```

详见 [`templates/接入说明.md`](templates/接入说明.md)。

### 四、跑 LLM Judge（生成层指标）

```bash
export RAG_JUDGE_BASE_URL=https://api.deepseek.com/v1    # 任意 OpenAI 兼容端点
export RAG_JUDGE_API_KEY=sk-xxx
export RAG_JUDGE_MODEL=deepseek-chat

python -m rag_eval.cli judge --dataset dataset/dataset_v1.jsonl --run-log logs/baseline.jsonl \
    --out results/judge_scores.json

# 有 100~300 条人工标注时，校准 Judge 可信度
python -m rag_eval.cli calibrate --judge-scores results/judge_scores.json \
    --human-labels human_labels.jsonl

# 把 Judge 判定注入评测（优先级：LLM Judge > 人工标注 > 规则）
python -m rag_eval.cli run --dataset dataset/dataset_v1.jsonl --run-log logs/baseline.jsonl \
    --judge-scores results/judge_scores.json
```

`calibrate` 在 Cohen's κ < 0.6 时退出码为 1，可直接当 CI 闸门，防止 rubric 被改坏。

---

## 命令速查

| 命令 | 作用 | 需 LLM |
|---|---|---|
| `validate` | 校验答题卡：schema + 跨行一致性 + 指标层覆盖率 | 否 |
| `run` | 确定性评测：检索/系统指标 + 错误归因 + 题型行业分组 + Pareto | 否 |
| `judge` | LLM-as-a-Judge 打分（Faithfulness / Correctness / Context 等） | 是 |
| `calibrate` | Judge 与人工标注算 Cohen's κ，κ<0.6 不放量 | 否 |
| `make-public` | 发卷：剥离标准答案与泄题字段 | 否 |
| `pack` | 打包参赛方工具箱 zip | 否 |

```bash
python -m rag_eval.cli <命令> --help
```

---

## 核心概念

### 1. 答题卡是唯一接入点

被测系统不需要用我们的框架。跑一遍考卷，把结果按格式存成 `run_log.jsonl` 即可：

```json
{"system_name": "team-A", "question_id": "ent_001",
 "answer": "…", "abstained": false,
 "retrieved_chunks": [{"chunk_id": "travel_policy_2025__005", "doc_id": "…", "rank": 1, "score": 0.87, "text": "…"}],
 "context": "真正送给 LLM 的完整上下文",
 "citations": [{"claim": "…", "chunk_id": "…"}],
 "latency_ms": 1280, "input_tokens": 3200, "output_tokens": 500, "error": null}
```

必填只有 3 个：`system_name` / `question_id` / `answer`。

### 2. 给多少字段，评多少指标

| 提供了 | 能评什么 |
|---|---|
| 只有 `answer` | Answer Correctness / Relevance / Completeness / Abstention |
| + `retrieved_chunks` | + Recall@K / Precision@K / MRR@K / NDCG@K |
| + `context` | + Context Recall/Precision、Faithfulness |
| + `citations` | + Citation 系列 |
| + `latency_ms` / `tokens` | + P95 延迟、cost/query、Pareto 图 |

缺字段显示 **N/A，不计 0 分**。这样设计是为了堵博弈漏洞——否则最优策略是只交 answer，检索层不交就不扣分。排行榜会标注覆盖率。

### 3. chunk 必须用官方编号

`ground_truth_chunks` 按 `corpus/chunks.jsonl` 的编号标注（`<doc_id>__<NNN>`，每个 `## ` 小节一个 chunk）。
被测系统自行重新切分会导致 chunk_id 对不上，检索层指标全算不出来。对照表在 `corpus/chunk_index.json`。

**可自由调整**：Embedding / BM25 / Hybrid / Reranker / Top-K / Query Rewrite / Prompt / LLM
**必须固定**：chunk 切法（用 `python corpus/build_corpus.py` 生成的官方库）

### 4. 判定来源优先级

`LLM Judge > 人工标注 > 规则版 approx_correct`

`results.json` 的 `judge` 字段会如实标注本次用了哪种判定，不冒充。

---

## 指标一览

| 层 | 指标 | 计算方式 |
|---|---|---|
| 检索 | Hit@K / Recall@K / Precision@K / MRR@K / NDCG@K，K∈{1,3,5,10} | 公式，NDCG 用 0-3 分级相关度 |
| 上下文 | Context Recall / Context Precision | LLM Judge |
| 生成 | Faithfulness / Answer Correctness / Answer Relevance / Completeness | LLM Judge |
| 引用 | Citation Precision / Recall / Correctness | 规则 + Judge |
| 拒答 | Abstention Accuracy | 规则 |
| 系统 | P50/P95/P99 延迟、cost/query、error/timeout rate | 公式 |
| 归因 | Retrieval / Ranking / Context / Generation / Citation / No-answer / System Error | 决策树 |

**错误归因**是本工具的差异点：答错的题会定位到该改哪个组件（Embedding → Reranker → Chunking → Prompt → 引用/消歧 → 拒答策略）。
比如「正确证据已进 context 却引了旧版本 chunk」归因为 **Citation Error**，提示改时间消歧而不是动 Prompt。

---

## 目录结构

```
schemas/          4 份数据契约（JSON Schema）
  dataset.schema.json          完整考卷（含标准答案，主办方持有）
  dataset_public.schema.json   公开考卷（发给参赛方）
  run_log.schema.json          答题卡
  human_labels.schema.json     人工复核标注

corpus/
  domains.json      行业注册表（10 个行业，2 active + 8 planned）
  enterprise/       企业制度语料 10 份
  ecommerce/        电商零售语料 10 份
  build_corpus.py   切分 + 编号 + 生成对照表
  chunks.jsonl      官方 chunk 库（114 个）
  chunk_index.json  chunk_id → 文档/行号 对照表
  baseline.py       朴素关键词检索 baseline（地板分）

dataset/
  dataset_v1.jsonl          完整考卷 50 题（2 行业 × 8 题型）
  dataset_public.jsonl      公开版（make-public 的产物）
  dataset_sample.jsonl      8 条格式样例（含埋坑场景，当测试夹具用）
  domains/<domain>.jsonl    分行业出题，补行业 = 加文件

rag_eval/
  validate.py       两层校验（schema + 跨行一致性）+ 覆盖率
  retrieval.py      Hit/Recall/Precision/MRR/NDCG
  system.py         延迟分位数、Token、成本、错误率
  triage.py         六类错误归因决策树
  aggregate.py      聚合、题型/行业分组、Pareto 前沿
  judge.py          OpenAI 兼容 Judge 客户端（温度 0、JSON 强制、3 次取中位）
  judge_metrics.py  指标组装与聚合
  calibration.py    Cohen's κ 校准与放量闸门
  pack.py           发卷剥离 + 泄题自检 + 工具箱打包
  cli.py            命令行入口

prompts/            6 份评分细则（一指标一文件，改 rubric 不动代码）
templates/          adapter_template.py + 接入说明.md（发给参赛方）
tests/              冒烟测试（P2 指标链 / P4 泄题回归）
logs/               答题卡（示例 + baseline）
results/            评测输出（仅保留 results_sample.json 作输出契约样例）
```

---

## 常用操作

### 补一个新行业

完整版目标是覆盖各行各业，补行业不用改代码：

1. `corpus/domains.json` 注册行业，`status` 置 `active`
2. 建 `corpus/<domain>/`，放若干 `.md` 语料（`## ` 小节切分）
3. `python corpus/build_corpus.py` 重新生成 chunk 库与对照表
4. 建 `dataset/domains/<domain>.jsonl`，按 8 种题型出题
5. 合并：把各行业 jsonl 拼成新的 `dataset_v1.jsonl`，跑 `validate`

### 改评分细则

`prompts/<metric>.md` 里直接改，注意三处：
- 评分标准 1-5 的分档描述
- 「特别注意」里的误判防护（例如「版本混淆算噪声」「限定词丢失扣档」）
- 输出 JSON 契约不要动

改完必须重跑 `calibrate`，κ < 0.6 说明改坏了。

### 自定义权重出排名

默认**不给总分**（不同业务权重不同，见《检测RAG质量.md》§56）。若赛制必须有名次，从 `results.json` 取各维度归一化值自行加权；Dashboard 会提供权重滑块。

### 跑测试

```bash
PYTHONPATH=. python tests/test_p2.py     # 指标链 / 校准闸门
PYTHONPATH=. python tests/test_pack.py   # 泄题回归（含负向用例）
```

---

## 已知局限

1. **演示语料的分数不能用来比真人**。当前语料是虚构的（上海云启科技 / 云启商城），跑分只验证工具链。真实开赛需换真实语料重出考卷。
2. **文件提交弱防作弊**。答题卡可手改。建议保留随机抽测权（抽 10 题现场重跑比对）；更彻底的做法是要求对方暴露 `POST /ask` 由本方统一跑题（尚未实现）。
3. **规则版正确性判定只是过渡**。`approx_correct` 用「标准答案里的数字是否都出现在回答里」做锚定，抓版本混淆有效但抓不到语义等价/漏答。生产使用请跑 LLM Judge 并做 κ 校准。
4. **Chunk 切法是固定的**。想测自己的切分策略属于另一个独立实验，不计入这场比试。

---

## 参考

- **[`docs/项目导览.md`](docs/项目导览.md)** —— 项目全景：架构、六大模块、**八个关键设计决策**
  （「为什么这么设计」的部分从代码里读不出来，改代码前请先看第五节）
- [`检测RAG质量.md`](检测RAG质量.md) —— 指标定义、题型设计、错误归因决策树的完整推导
- [`RAG评测可视化工具-方案.md`](RAG评测可视化工具-方案.md) —— 架构与实施计划
