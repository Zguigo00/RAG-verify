# RAG 质量评测工具箱

用你自己的 RAG 答 50 道题，交回一份答题卡，我们统一评分并出对比报告。

**怎么用**：解压 → 填一个函数 → 跑题 → 自查 → 交回 `run_log.jsonl`。5 分钟接入。

---

## 一、不限语言 —— 你的 RAG 用什么写都行

我们**不调用、不嵌入**你的代码，只读一份答题卡文件（`run_log.jsonl`，每行一个 JSON）。
Java / Go / Node / Rust / C# / Python 都行，甚至手填也可以。

| 你的形态 | 怎么做 |
|---|---|
| **有 Python 代码** | 用 `templates/adapter_template.py`，改一个函数即可 |
| **有 Java / Go / Node 等代码** | 用你自己的语言产出 `run_log.jsonl`，格式见第二节 |
| **只有网页界面**（Dify / Coze / 扣子 / 自建站点） | 把考题复制进去问，把回答贴回 CSV 发我们，我们代转答题卡（此时只能评生成层） |
| **不方便装 Python 自查** | 直接把答卷发回来，我们代验；或用任意 JSON Schema 库跑 `schemas/run_log.schema.json`（公开标准，各语言都有实现） |

自查工具是 Python，但**不是交卷的必要条件**。

---

## 二、答题卡长什么样

每行一个 JSON 对象，对应一道题。**必填只有 3 个字段**：`system_name` / `question_id` / `answer`。

### 最小可行（只评生成层指标）

```json
{"system_name": "my-team", "question_id": "ecom_001", "answer": "7 天内可无理由退货。"}
```

### 完整形态（全指标可评）

```json
{
  "system_name": "my-team",
  "question_id": "ecom_001",

  "answer": "自签收之日起 7 天内可无理由退货，每月同一商品不超过 3 次。",
  "abstained": false,
  "query_rewritten": "无理由退货期限 几天",

  "retrieved_chunks": [
    {"chunk_id": "return_policy_2025__001", "doc_id": "return_policy_2025", "rank": 1, "score": 0.87, "text": "…"},
    {"chunk_id": "return_policy_2024__001", "doc_id": "return_policy_2024", "rank": 2, "score": 0.81, "text": "…"}
  ],

  "context": "[1] ## 无理由退货\n除特殊商品外，自签收之日起 7 天内…\n[2] …",
  "citations": [{"claim": "7 天内可无理由退货", "chunk_id": "return_policy_2025__001"}],

  "latency_ms": 1280,
  "input_tokens": 3200,
  "output_tokens": 120,
  "cost_usd": 0.012,
  "trace": {"embedding_ms": 45, "search_ms": 80, "rerank_ms": 200, "llm_ms": 900},
  "error": null
}
```

可选字段**没提供就整个省略，或显式填 `null`**，两种都接受，效果一样（该指标显示 N/A，不计 0 分）。

### Node.js 产出示例

```js
// producer.mjs
import fs from 'node:fs';
import { ask } from './my-rag.mjs';          // 你自己的 RAG

const questions = fs.readFileSync('dataset/dataset_public.jsonl', 'utf8')
  .trim().split('\n').map(JSON.parse);

const out = [];
for (const q of questions) {
  const r = await ask(q.question);
  out.push({
    system_name: 'my-team',
    question_id: q.question_id,
    answer: r.answer,
    abstained: false,
    retrieved_chunks: r.chunks.map((c, i) => ({
      chunk_id: c.id, doc_id: c.doc, rank: i + 1, score: c.score, text: c.text,
    })),
    context: r.context,
    latency_ms: r.latencyMs,
    error: null,
  });
}
fs.writeFileSync('run_log.jsonl', out.map(JSON.stringify).join('\n') + '\n');
```

### Java 产出示例

```java
// 逐行读考卷 -> 逐题问答 -> 逐行写 JSONL。Jackson / Gson / Fastjson 均可。
try (var w = Files.newBufferedWriter(Path.of("run_log.jsonl"), StandardCharsets.UTF_8)) {
    for (var q : questions) {
        var t0 = System.nanoTime();
        var r = myRag.ask(q.question());                 // 你自己的 RAG
        var node = mapper.createObjectNode();
        node.put("system_name", "my-team");
        node.put("question_id", q.questionId());
        node.put("answer", r.answer());
        node.put("latency_ms", (System.nanoTime() - t0) / 1_000_000);
        var arr = node.putArray("retrieved_chunks");     // 见第二节格式
        r.chunks().forEach(c -> { var o = arr.addObject();
            o.put("chunk_id", c.id()); o.put("doc_id", c.doc());
            o.put("rank", c.rank()); o.put("text", c.text()); });
        w.write(mapper.writeValueAsString(node));
        w.newLine();
    }
}
```

> 提示：Java 的 `Map.of` / Go 的 `map` 不接受 null，直接**省略**没提供的字段即可。

### 暴露 HTTP 接口（最公平，推荐正式比赛用）

任意语言实现一个路由，我们统一代跑、统一计时：

```http
POST /ask
{"question_id": "ecom_001", "question": "买了衣服不合适，几天内能无理由退货？"}

-> 200
{"answer": "…", "abstained": false, "retrieved_chunks": [...], "context": "…"}
```

---

## 三、第 0 步：零代码冒烟测试（建议先做）

**不用写任何代码**，先确认工具箱在你机器上跑得通：

```bash
pip install -r requirements.txt

# 用工具箱自带的朴素关键词检索，跑 3 题
python corpus/baseline.py --dataset dataset/dataset_public.jsonl --out run_log.jsonl --limit 3

# 自查
python -m rag_eval.cli validate --dataset dataset/dataset_public.jsonl --run-log run_log.jsonl
```

期望输出：

```
[读取] dataset_records: 50 条
[读取] dataset 版本: public
[读取] run_log:run_log.jsonl: 3 条
...
[结果] 0 个错误, 0 个警告        ← 看到这个就说明环境没问题
```

跑通之后再开始改 `adapter_template.py`。这样如果后面报错，能确定是自己代码的问题而不是环境问题。

> 这个 baseline 是纯词面匹配（无 embedding、无 rerank、无 LLM）的地板分，
> 你的 RAG 理应比它强。也可以用它来对照自己的检索是否正常：
> ```bash
> python corpus/baseline.py --dataset dataset/dataset_public.jsonl --out baseline.jsonl
> python -m rag_eval.cli run --dataset dataset/dataset_public.jsonl --run-log baseline.jsonl
> ```
> （注意：`run` 需要标准答案，所以只有主办方能出分。你本地能看的是 `validate` 的覆盖率。）

---

## 四、3 步接入（Python 路线）

```bash
pip install -r requirements.txt          # 只有 jsonschema 一个依赖

# 1. 改 templates/adapter_template.py，实现里面的 ask(question)
# 2. 跑题（先 --limit 5 调通格式）
python templates/adapter_template.py --dataset dataset/dataset_public.jsonl --out run_log.jsonl --limit 5

# 3. 自查，0 个错误才能交
python -m rag_eval.cli validate --dataset dataset/dataset_public.jsonl --run-log run_log.jsonl
```

`ask()` 三种典型写法，模板注释里都有：

```python
def ask(question: str) -> dict:
    # (a) 直接调函数
    r = my_rag_chain.invoke(question)

    # (b) 调本地 HTTP 服务
    # r = requests.post("http://127.0.0.1:8000/ask", json={"question": question}, timeout=30).json()

    # (c) 自己检索 + 调 OpenAI 兼容接口
    # ctx = my_retriever.search(question, top_k=5)
    # r = {"answer": my_llm.chat(question, ctx), "retrieved_chunks": ctx, "context": format(ctx)}

    return {"answer": r["answer"], "retrieved_chunks": r["chunks"], "context": r["context"]}
```

字段名做了别名兼容：LangChain 的 `page_content`、LlamaIndex 的 `text`、自研的 `content` 都能自动识别，多数人一行都不用改。

---

## 五、必读的 1 条硬规则：检索要用官方 chunk

请从 `corpus/chunks.jsonl` 这个**固定 chunk 库**检索，并如实返回官方 `chunk_id`
（格式 `<doc_id>__<NNN>`，对照表在 `corpus/chunk_index.json`）。

原因：标准答案是按这套编号标的。若自行重新切分，chunk_id 对不上，
**Recall@K / Precision@K / MRR / NDCG 一个都算不出来**，等于白交。

| 可自由调整 | 必须固定 |
|---|---|
| Embedding 模型、BM25 / Hybrid、Reranker、Top-K、Query Rewrite、Prompt、LLM | chunk 切法（每个 `## ` 小节 = 1 个 chunk） |

想测你独特的切分策略，那是另一场独立实验，请单独说明，不计入本场比试。

### 非官方 ID 系统如何对齐

很多检索引擎（Chroma / Milvus / ES / 自研）用 md5 或自增 ID，不产出官方 `chunk_id`。不要改检索算法，
把官方编号**塞进元数据再取出来**即可：

```python
# 入库时：把官方 chunk_id 写进 metadata
collection.upsert(
    ids=[c["chunk_id"] for c in chunks],          # 直接用官方编号当 Chroma ID，最省事
    documents=[c["text"] for c in chunks],
    metadatas=[{"chunk_id": c["chunk_id"], "doc_id": c["doc_id"]} for c in chunks],
)

# 检索后：从 metadata 取回官方编号，填进答题卡
retrieved_chunks = [
    {"chunk_id": m["chunk_id"],                   # ← 不是你的自产 ID
     "doc_id":   m["doc_id"],
     "rank":     i + 1,
     "score":    r["score"],
     "text":     r["text"]}
    for i, (m, r) in enumerate(zip(metadatas, results))
]
```

`search()` 只返回 `{"text","source","distance"}` 之类的系统同理 —— `source` 里存官方编号即可。
填完跑 `python -m rag_eval.cli validate`，它会逐条核对编号是否在 `corpus/chunk_index.json` 里，
填错指到行号。

---

## 六、给多少字段，评多少指标

| 你提供了 | 能评什么 |
|---|---|
| 只有 `answer` | Answer Correctness / Relevance / Completeness / Abstention |
| + `retrieved_chunks` | 再加 **Recall@K / Precision@K / MRR / NDCG** |
| + `context` | 再加 **Context Recall / Context Precision / Faithfulness** |
| + `citations` | 再加 **Citation 系列** |
| + `latency_ms` / `tokens` / `cost_usd` | 再加 **P95 延迟、cost/query、Pareto 图** |

缺字段显示 **N/A，不计 0 分**，但排行榜会标注你的覆盖率。

**强烈建议给到 `retrieved_chunks` + `context`**：只交最终答案就退化成普通问答评测，而且一旦答错，
无法判断是**没找到**还是**没用好** —— 你自己也拿不到那份「该改 Embedding 还是改 Prompt」的诊断报告。

---

## 七、5 个最容易踩的坑

1. **`rank` 必须从 1 开始连续不重复**（校验会拦，错误信息指到具体行号）
2. **`context` 是「真正送给 LLM 的那段文字」**，不是原始文档，也不是只有摘要。
   截断了要如实反映：「正确 chunk 检索到了却没进 context」会归因为 **Context Error**，与「根本没搜到」是两回事
3. **无答案题要敢拒答**：`abstained: true` + `answer` 写「根据现有知识库，无法找到相关信息」。
   硬编一个答案会被计为幻觉（No-answer Error），这项权重很高
4. **`citations` 的 `claim` 写你答案里的原句**，不是你的解释。引用错了单独算 Citation Correctness
5. **超时照实填**：`answer` 填 `""`、`error` 写原因。谎报成功比超时扣分更狠

---

## 八、你会拿到什么

1. **Scorecard**：你的各项指标 + 全场对比（每列最优高亮）
2. **错误归因报告**：答错的题定位到该改哪个组件
   （Retrieval → Ranking → Context → Generation → Citation → No-answer 六类，附建议）
3. **题型 / 行业雷达图**：8 种题型、多行业的强弱分布
4. **逐题复核页面**：每题你的答案、检索到的 chunk（命中标准答案会高亮）、判分理由

---

## 九、防作弊边界（如实声明）

文件提交模式下，**自报的中间过程无法被技术验证**。评测方承认以下边界：

| 可验证 | 不可验证（依赖诚信） |
|---|---|
| 答题卡格式、题号完整性 | `retrieved_chunks` 是否真是系统检索所得 |
| `chunk_id` 是否为官方编号 | `context` 是否真是送给 LLM 的文本 |
| `chunk` 的 `text` 与官方原文是否一致 | `citations` 是否是实时生成 |
| `input_tokens` 与 `context` 长度是否大致匹配 | `latency_ms` 是否真实 |
| `rank` 与 `score` 的单调性 | 无答案题是否真走了拒答逻辑 |
| `answer` 与 `retrieved_chunks` 的一致性（抽测） | — |

评测方保留三类手段，请按诚信要求填写：

1. **一致性审计**（`rag-eval audit`）：对可验证项做异常信号检测
   —— score 非单调、context 与 token 数严重不符、latency 与耗时不符、text 与官方原文不符等。
   命中即标为可疑，人工复核。
2. **暗题抽测**：主办方保留一部分题目不公开，收官时补测，用于击穿「离线标注标准答案后硬编码」。
3. **现场复跑**：随机抽题当面重跑，比对 answer 与 chunks 是否一致。

**硬编码答题卡（离线标好标准 chunk_id 直接填）虽然可能骗过单次评测，但属于作弊**。
这类行为一旦在复跑或暗题中暴露，成绩作废。内部/教学场景请按诚信填写 —— 评测的目的是诊断你 RAG 的短板，
刷分只会让你拿不到那份「该改 Embedding 还是改 Prompt」的有用结论。

---

## 十、里面有什么

```
README.md                        本文件
dataset/dataset_public.jsonl     考卷 50 题（只有题目，无答案）
corpus/chunks.jsonl              语料库 114 个 chunk —— 必须从这里检索
corpus/chunk_index.json          chunk_id -> 文档/行号 对照表
corpus/<domain>/*.md             原始语料 20 份（企业制度 + 电商零售）
schemas/                         4 份数据契约（JSON Schema，各语言通用）
templates/adapter_template.py    接入模板（Python）
templates/接入说明.md             详细接入规则
rag_eval/                        校验工具（自查用）
requirements.txt                 依赖（只有 jsonschema）
```

语料全部为虚构演示语料（上海云启科技有限公司 / 云启商城），数字为编造值。
内含多套年度版本（差旅 2024/2025、退换货 2024/2025、会员 2024/2025）与两套促销规则（618 / 双11），
请自行做好版本消歧。

有问题直接联系主办方。
