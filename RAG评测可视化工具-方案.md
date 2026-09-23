# RAG 质量评测与可视化工具 —— 建设方案

## 0. 定位与场景

**场景**：多人/多队各自实现一套 RAG，在**同一测试集**上比出谁更好，并且能解释「为什么好、差在哪一环」。

**核心原则**（来自《检测RAG质量.md》）：

1. 不只看最终答案 —— 按 数据 → 检索 → 重排 → 上下文 → 生成 → 答案 分层测
2. 不只看平均值 —— 按题型（simple / multi-hop / no-answer / temporal…）拆分
3. 不迷信单一总分 —— 用 Pareto + 可调权重，而非一个 Universal Score
4. 评测必须能指导优化 —— 错误归因（Retrieval / Ranking / Context / Generation / Citation / No-answer）

---

## 1. 总体架构

三个模块松耦合，模块间用 **JSON/JSONL 文件**做契约（方便留档、复现、离线跑）：

```
[参赛方 RAG 系统]  (任意实现：LangChain / LlamaIndex / 自研)
        │
        │  ① 统一提交格式 run_log.jsonl   ←—— 本工具定义的唯一接入点
        ▼
[评测引擎 rag-eval]  ←—— 测试集 dataset.jsonl + 评分细则 rubric + Judge 模型
        │
        │  ② results.json  (逐题明细 + 聚合指标 + 错误归因)
        ▼
[可视化 Dashboard]   ←—— 人工复核 human_labels.jsonl
        │
        │  ③ scorecard.xlsx / report.html / report.pdf
        ▼
   [评委 / 汇报]
```

**关键设计：评测工具不侵入对方实现**，只认提交的 run log。谁用什么框架都行，保证横向可比。

---

## 2. 统一数据标准（最重要，先做）

### 2.1 测试集 `dataset.jsonl`（每题一条）

```json
{
  "question_id": "q001",
  "question": "员工出差每天可以报销多少住宿费？",
  "category": "simple",
  "difficulty": "easy",
  "ground_truth_answer": "国内一线城市住宿费标准为800元/天。",
  "ground_truth_chunks": [
    {"chunk_id": "chunk_183", "doc_id": "employee_travel_policy.pdf", "relevance": 3}
  ],
  "ground_truth_facts": ["一线城市住宿标准为800元/天"],
  "expected_abstain": false
}
```

| 字段 | 用途 |
|---|---|
| `category` | `simple / multi_hop / long / temporal / ambiguous / no_answer / multi_doc / hard` —— 分类别统计（文档 §44） |
| `ground_truth_chunks[].relevance` | 0-3 分级，供 NDCG 计算（文档 §21） |
| `ground_truth_facts` | 拆成原子事实，供 Context Recall / Completeness |
| `expected_abstain` | `true` 时该题为无答案题，测 Abstention Accuracy（文档 §47） |

**题型配比**（文档 §58）：开发期 200 条，正式 800~1000 条。
`simple 200 / multi_hop 150 / long 150 / temporal 100 / multi_doc 100 / no_answer 100 / ambiguous 100 / hard 100`

### 2.2 提交结果 `run_log.jsonl`（每题一条）

```json
{
  "system_name": "team-A",
  "question_id": "q001",
  "query_rewritten": "出差住宿报销标准",
  "retrieved_chunks": [
    {"chunk_id": "chunk_183", "doc_id": "employee_travel_policy.pdf",
     "score": 0.87, "rank": 1, "text": "…"}
  ],
  "context": "拼接后送给 LLM 的完整上下文",
  "answer": "国内一线城市住宿费标准为800元/天。",
  "citations": [{"claim": "住宿费标准为800元/天", "chunk_id": "chunk_183"}],
  "abstained": false,
  "latency_ms": 1280,
  "input_tokens": 3200,
  "output_tokens": 500,
  "trace": {"embedding_ms": 45, "search_ms": 80, "rerank_ms": 200, "llm_ms": 900},
  "error": null
}
```

- **最低接入成本**：只给 `question_id + answer` 也能算 Correctness / Relevance；给了 `retrieved_chunks` 才算检索指标。字段缺失 → 对应指标显示 N/A，不作弊式补 0。
- `trace` 可选，有就能画耗时火焰图。

### 2.3 人工复核 `human_labels.jsonl`

```json
{"question_id": "q001", "system_name": "team-A", "labeler": "alice",
 "correct": 1, "faithful": 1, "complete": 1, "citation_ok": 1, "note": ""}
```

### 2.4 防作弊（可选但建议）

- **A 模式（文件提交）**：组织方随机抽 30 题现场复跑，比对 answer 与 chunks 一致性。
- **B 模式（接口调用）**：各队暴露 `POST /ask {question} -> {answer, retrieved_chunks, ...}`，由评测方统一跑，天然防作弊。

---

## 3. 评测引擎 `rag-eval`

Python 包。CLI：

```bash
rag-eval run   --dataset dataset.jsonl --run logs/team-A.jsonl --out results/team-A.json
rag-eval judge --results results/ --judge-model gpt-4o --calib human_labels.jsonl
rag-eval report --results results/ --out report/
```

### 3.1 指标分层（对齐文档 §34 推荐表 + §59 优先 8 项）

| 层 | 指标 | 计算方式 | 需 LLM |
|---|---|---|---|
| Retrieval | Recall@1/3/5/10, Precision@5/10, MRR@5/10, NDCG@5/10 | 确定性公式 | 否 |
| Context | Context Recall / Context Precision / Context Relevance | LLM-judge | 是 |
| Generation | Faithfulness / Answer Correctness / Answer Relevance / Completeness | LLM-judge | 是 |
| Citation | Citation Precision / Recall / Correctness / Completeness | 规则+judge | 部分 |
| Abstention | Abstention Accuracy | 规则（拒答判定） | 可选 |
| System | P50/P95/P99 latency, tokens, cost/query, error/timeout rate | 确定性 | 否 |
| Robustness | no-answer / ambiguous / temporal / typo / conflict 分组表现 | 分组聚合 | 否 |

**优先实现 10 项**（文档 §59）：Recall@5、MRR@5、NDCG@5、Context Precision、Context Recall、Faithfulness、Answer Correctness、Answer Relevance、Citation Correctness、Abstention Accuracy。

### 3.2 LLM-as-a-Judge（文档 §48-50）

- **每个指标一个独立 prompt**，输出结构化 JSON：`{"score": 1-5, "evidence": "...", "reason": "..."}`，强制 JSON Schema 校验 + 失败重试。
- **温度 0**，走 OpenAI 兼容接口（Claude / Qwen / DeepSeek / 本地 vLLM 均可）。
- **降方差**：每条样本 3 次取平均（可开关），报告里给标准差。
- **Judge 校准（必须做）**：抽 100~300 条人工标注，算一致率 + Cohen's κ。κ < 0.6 就改 rubric，不达标不放大到全量（文档 §50）。

### 3.3 错误归因（文档 §53-54）—— 工具差异化亮点

对每个答错的题按决策树打标：

```
答错？
 ├─ 正确 chunk 不在 retrieved          → Retrieval Error     (改 Embedding/BM25/Hybrid)
 ├─ 在 retrieved 但没进 context / 排名靠后 → Ranking Error       (改 Reranker / Top-K)
 ├─ 在 context 但被截断 / 版本错        → Context Error       (改 Chunking / Parent-doc / Filtering)
 ├─ 在 context 且完整但答案错           → Generation Error    (改 Prompt / LLM)
 ├─ 答案对但引用错                     → Citation Error      (改引用生成逻辑)
 └─ 无答案题却作答                     → No-answer Error     (幻觉，改拒答策略)
```

聚合出每个系统的 **error breakdown**，直接给出「该优化 Embedding 还是 Reranker 还是 Prompt」的结论。这比 `Accuracy = 87%` 有价值一个量级。

---

## 4. 可视化 Dashboard

**选型**：一期 **Streamlit**（Python 单栈、1 天出原型、图表够用）；二期若要对外产品化，换 **FastAPI + React + ECharts**。另加「一键导出静态 HTML」方便发邮件/贴 PPT。

### 页面结构（7 个 Tab）

**T1 排行榜 Leaderboard**
- 主表 = 文档 §55 的 Scorecard：多列指标，**每列最优高亮**，默认**不给总分**
- **权重滑块**（检索/上下文/生成/引用/系统 5 组），实时算加权分并重排 —— 既能回答"谁更好"，又把"好"的定义交给评委（文档 §56 警告）
- 排名随权重变化的 **bump chart**，暴露排名对权重的敏感性

**T2 多维对比**
- 雷达图：5 大维度归一化，一眼看谁更全面
- 分组柱状图：§59 的 10 个优先指标并排

**T3 分类别热力图**（题型 × 指标 × 系统）
- 落实"不要只看平均值"（文档 §44），直接暴露「B 系统 no-answer 只有 72%」这类短板

**T4 错误归因**
- 堆叠条形图（6 类错误）+ 点击下钻到具体题目和 chunk

**T5 Pareto 散点图**
- x = Latency(P95)，y = Answer Correctness，气泡大小 = Cost/query（文档 §57）
- 画出 Pareto 前沿，直观展示「质量 vs 延迟 vs 成本」trade-off

**T6 逐题 Case 对比**（人工复核主界面，最重要）
- 选一题 → 各系统答案并排 + 各自 retrieved chunks（命中 ground truth 高亮）+ judge 评分与理由
- 人工可改标，改标数据回写 `human_labels.jsonl`
- 支持按「judge 分歧最大 / 分数方差最大」排序，优先复核最不确定的题

**T7 Judge 一致性**
- LLM vs 人工：一致率、Cohen's κ、混淆矩阵（文档 §50）

**导出**：`scorecard.xlsx`（§55 表）+ `report.html` + 原始 `results.json`

---

## 5. 实施计划（约 1.5 周 / 单人）

| 阶段 | 内容 | 产出 | 工时 |
|---|---|---|---|
| **P0 数据标准** | 3 个 JSONL schema + 校验器 + 样例数据 | `schemas/` + `rag-eval validate` | 0.5d |
| **P1 无 LLM 指标** | Recall/Precision/MRR/NDCG + Abstention + System + 错误归因规则部分 | `rag_eval/retrieval.py`, `system.py`, `triage.py` | 1d |
| **P2 LLM Judge** | 生成 4 指标 + Context 3 指标 + 校准流程 | `rag_eval/judge.py` + `prompts/` | 1.5d |
| **P3 Dashboard** | 7 个 Tab + 权重滑块 + 导出 | `app.py` (Streamlit) | 2.5d |
| **P4 测试集** | 8 类题型 200 条（LLM 生成 + 人工校） | `dataset_v1.jsonl` | 1.5d |
| **P5 联调** | 2 个 baseline RAG（纯向量 / 向量+BM25+rerank）跑通全链路 | demo 结果 + 报告 | 1d |

**里程碑验收标准**：
1. 用文档 §35 的 RAG A / RAG B 示例数据，能画出完整 Scorecard + 雷达图 + 错误归因
2. 报告能自动得出「B 的 Recall 更高但噪声拖累 Faithfulness」这类结论
3. 新系统接入 → 出报告 ≤ 30 分钟

---

## 6. 目录结构（建议）

```
RAGtest/
├── schemas/
│   ├── dataset.schema.json
│   ├── run_log.schema.json
│   └── human_labels.schema.json
├── dataset/
│   ├── dataset_v1.jsonl
│   └── build_dataset.py          # LLM 生成候选题 + 人工校对
├── rag_eval/
│   ├── retrieval.py              # Recall/Precision/MRR/NDCG
│   ├── context.py                # Context Recall/Precision (judge)
│   ├── generation.py             # Faithfulness/Correctness/Relevance/Completeness (judge)
│   ├── citation.py
│   ├── system.py                 # latency/tokens/cost
│   ├── triage.py                 # 错误归因决策树
│   ├── judge.py                  # LLM-judge 封装 + 校准
│   ├── aggregate.py              # 聚合 + 按题型分组 + Pareto
│   └── cli.py
├── app/                          # Streamlit
│   ├── app.py
│   ├── tabs/                     # T1~T7
│   └── export/                   # xlsx / html 导出
├── prompts/                      # judge prompts（一指标一文件，版本化）
├── logs/                         # 各系统 run_log
├── results/                      # 评测输出
├── human_labels.jsonl
└── 检测RAG质量.md
```

---

## 7. 待确认的关键决策

| # | 问题 | 选项 | 我的建议 |
|---|---|---|---|
| 1 | **接入方式** | A. 各队提交 run_log.jsonl（简单，弱防作弊）<br>B. 评测方统一调各队 `POST /ask`（强防作弊，要求部署）<br>C. 两者都支持 | 先做 A，留 B 接口 |
| 2 | **Judge 模型与预算** | Claude / GPT / Qwen / DeepSeek / 本地 | 用便宜的（DeepSeek/Qwen）跑全量，抽样用强模型复核 |
| 3 | **是否要官方总分名次** | Scorecard+Pareto（无总分） vs 固定权重总分 | 若必须排名，用**官方固定权重**出名次，但页面仍保留滑块让评委自己调 |
| 4 | **是否需要离线报告** | xlsx / html / pdf | 至少 xlsx + html |
| 5 | **测试集由谁出** | 你方统一出 vs 各队自带 | **必须统一**，否则不可比 |

---

## 8. 为什么这个方案能回答「谁的 RAG 更好」

1. **同一测试集 + 统一提交格式** → 横向可比（决策 #5 是前提）
2. **分层指标** → 不会因为 B 召回高就误判 B 好（§35 的教训）
3. **按题型拆分** → 揭穿「平均分高但 no-answer 一塌糊涂」
4. **Pareto + 可调权重** → 尊重「法律 RAG 重引用、客服 RAG 重延迟」的业务差异（§56）
5. **错误归因** → 赢的知道为什么赢，输的知道改哪里（§53-54, §60）
6. **人工复核 + Judge 一致性** → 结论经得起质疑（§49-50）

