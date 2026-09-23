可以。判断一个 RAG（Retrieval-Augmented Generation）系统“做得好不好”， **不能只看最终回答是否正确** 。最好把它拆成几个环节分别测：

> **数据/知识库 → 检索 → 重排 → 上下文构造 → LLM 生成 → 最终答案**

一个好的 RAG，核心不是“模型说话漂亮”，而是：

**该找的能找到、不该找的不乱找、找到的内容真的被模型利用、最终答案准确且有依据。**

下面我给你一个比较完整、可以真正落地的 RAG Evaluation（评测）体系。

---

假设你的 RAG 流程是：

```
用户问题
   ↓
Query Rewrite / Query Expansion
   ↓
Embedding
   ↓
Vector Search
   ↓
BM25 / Hybrid Search
   ↓
Reranker
   ↓
Top-K Context
   ↓
LLM
   ↓
最终答案
```

可以把质量拆成：

```
					RAG 质量
                      │
       ┌──────────────┼──────────────┐
       ↓              ↓              ↓
    Retrieval      Generation      End-to-End
     检索质量        生成质量          最终效果
       │              │              │
  ┌────┼────┐     ┌────┼────┐     ┌────┼────┐
  ↓    ↓    ↓     ↓    ↓    ↓     ↓    ↓    ↓
Recall Precision  Faithfulness  Correctness
MRR    NDCG       Groundedness  Relevance
Hit@K             Citation      Completeness
```

所以，如果你要比较： 

> RAG A 和 RAG B 哪个好？

应该比较的不只是最终答案，而是：

```
RAG A
├── Retrieval Recall
├── Precision
├── MRR
├── NDCG
├── Context Recall
├── Context Precision
├── Faithfulness
├── Answer Correctness
├── Answer Relevance
├── Citation Correctness
└── Latency / Cost

RAG B
├── ...
```

---

## 二、第一件事：一定要准备 Evaluation Dataset

这是整个 RAG Evaluation 最重要的部分。

如果没有测试集，你其实很难客观判断：

> “这个 RAG 比那个 RAG 好。”

因为你可能只是感觉：

> “这个回答看起来比较好。”

这不够。

---

## 三、怎么构造 RAG 测试集？

假设你做的是企业知识库。

例如知识库里有：

```
员工手册
产品文档
财务制度
销售制度
技术文档
FAQ
```

可以建立：

```json
{
  "question": "员工出差每天可以报销多少住宿费？",
  "ground_truth_answer": "国内一线城市住宿费标准为800元/天。",
  "ground_truth_documents": [
    "employee_travel_policy.pdf"
  ],
  "ground_truth_chunks": [
    "chunk_183"
  ]
}
```

这里有三个非常重要的东西：

### 1\. Question

用户的问题：

```
员工出差每天可以报销多少住宿费？
```

### 2\. Ground Truth Answer

标准答案：

```
国内一线城市住宿费标准为800元/天。
```

### 3\. Ground Truth Context

正确答案所在的文档 / chunk：

```
employee_travel_policy.pdf
chunk_183
```

这样才能评价：

> RAG 有没有找到正确内容？

---

## 四、测试集不要只有一种问题

这是很多 RAG Evaluation 做得不好的地方。

不要只有：

```
简单事实问题
```

应该至少分成下面几类。

---

## 1\. Single-hop Question

一个 chunk 就能回答。

例如：

```
公司的年假是多少天？
```

这种问题主要测试：

> 基础 Retrieval 能力。

---

## 五、Multi-hop Question

需要多个文档/多个 chunk。

例如：

```
如果员工在上海出差3天，
同时参加公司培训，
他的交通费和住宿费分别按照什么标准报销？
```

可能需要：

```
出差制度
+
培训制度
+
费用报销制度
```

这种问题特别适合测试：

> RAG 是否能够召回多个相关证据。

---

## 六、长问题

例如：

```
根据2025年公司的差旅制度，
分析北京、上海、深圳三个城市的住宿报销标准，
并说明不同职级员工有什么区别。
```

这种问题测试：

- retrieval
- context management
- reasoning
- generation

---

## 七、容易混淆的问题

例如：

```
2024年的报销标准是多少？
```

知识库里面可能有：

```
2022制度
2023制度
2024制度
2025制度
```

这个问题非常重要。

因为很多 RAG：

> 找到了“相关”的东西，但找错了版本。

所以应该加入：

```
Temporal Questions
```

---

## 八、无答案问题

这个非常重要。

例如知识库里面没有：

```
公司在东京有没有办公室？
```

但是 LLM 可能会：

> 根据常识编一个答案。

好的 RAG 应该回答：

```
根据现有知识库，无法找到相关信息。
```

而不是：

```
公司在东京设有办公室……
```

所以一定要测试：

> **Abstention / Unanswerable Questions**

也就是：

**知识库没有答案时，能不能正确拒答。**

---

## 九、同义表达

例如知识库写：

```
员工年度休假制度
```

用户问：

```
一年有几天假？
```

测试 embedding retrieval 能不能匹配。

---

## 十、口语问题

例如：

```
出差住酒店公司到底给不给报？
```

而文档写：

```
员工因公出差产生的住宿费用，在符合相关标准的情况下予以报销。
```

测试：

> Semantic Retrieval

---

## 十一、建立一个标准 Evaluation Dataset

实际项目我比较推荐：

```
500～2000 条问题
```

例如：

| 类型 | 数量 |
| --- | --- |
| Simple QA | 100 |
| Multi-hop | 100 |
| Long QA | 100 |
| Temporal | 100 |
| Ambiguous | 100 |
| No-answer | 100 |
| Multi-document | 100 |
| Hard cases | 100 |

总计：

```
800 questions
```

如果只是开发阶段：

```
100～300
```

也可以。

---

## 十二、第一大类：Retrieval Evaluation

首先不要让 LLM 生成答案。

单独测试：

> **RAG 到底有没有把正确的东西找出来。**

这是最重要的一步。

---

## 十三、Recall@K

最基础的指标。

假设：

```
Question:
员工出差住宿标准是多少？

正确 chunk:
chunk_183
```

RAG 返回：

```
Top 5

chunk_20
chunk_31
chunk_183
chunk_200
chunk_999
```

正确 chunk 在 Top 5。

所以：

```
Recall@5 = 1
```

如果：

```
Top 5

chunk_20
chunk_31
chunk_200
chunk_999
chunk_500
```

没有：

```
chunk_183
```

那么：

```
Recall@5 = 0
```

---

## 十四、Recall@K 怎么算？

假设有：

```
100 个问题
```

对于每个问题，我们知道正确 chunk。

如果：

```
Top-K 找到正确 chunk
```

就记：

```
1
```

否则：

```
0
```

那么：

```
Recall@K =
成功找到的问题数 / 总问题数
```

例如：

```
100 个问题
Top 5 找到 87 个
```

那么：

```
Recall@5 = 87%
```

---

## 十五、Recall@1 / Recall@3 / Recall@5 / Recall@10

建议全部测。

例如：

| RAG | Recall@1 | Recall@3 | Recall@5 | Recall@10 |
| --- | --- | --- | --- | --- |
| A | 71% | 85% | 91% | 95% |
| B | 76% | 89% | 93% | 97% |

可以发现：

B 的 Retrieval 整体更强。

---

## 十六、但是 Recall@K 有一个问题

比如：

```
Top 10
```

里面可能：

```
1个正确
9个垃圾
```

Recall 还是：

```
100%
```

所以：

> Recall 高，不代表 Retrieval 好。

这就需要：

## Precision@K

---

## 十七、Precision@K

例如：

Top 5：

```
chunk_1  ❌
chunk_2  ✅
chunk_3  ❌
chunk_4  ❌
chunk_5  ❌
```

只有一个相关 chunk。

那么：

```
Precision@5 = 1 / 5 = 20%
```

---

## 十八、Recall 和 Precision 的区别

可以简单理解：

### Recall

> 正确答案有没有被找到？

### Precision

> 找出来的东西，有多少是真的有用？

所以：

```
Recall = 找没找到
Precision = 找出来的准不准
```

RAG 非常常见的问题：

```
Recall 很高
Precision 很低
```

也就是：

> 什么都搜到了，但是 Top-K 里面塞了一堆垃圾。

---

## 十九、MRR

MRR：

**Mean Reciprocal Rank**

它关注：

> 正确答案排在第几位？

例如：

```
RAG A:

Top 1 → 正确
```

那么：

```
RR = 1
```

如果：

```
Top 2 → 正确
```

那么：

```
RR = 1/2 = 0.5
```

如果：

```
Top 5 → 正确
```

那么：

```
RR = 1/5 = 0.2
```

最终：

```
MRR = 所有问题 RR 的平均值
```

---

## 二十、为什么 MRR 很重要？

假设：

```
RAG A:
正确 chunk 平均排名第2

RAG B:
正确 chunk 平均排名第8
```

即使两个 RAG 的 Recall@10 一样：

```
Recall@10 = 95%
```

实际上 A 通常更适合 RAG。

因为 LLM 能看到的有效 context 是有限的。

---

## 二十一、NDCG@K

NDCG 比 Recall / Precision 更适合复杂 Retrieval。

因为现实里面：

> 一个问题可能有多个相关 chunk。

例如：

```
chunk A：非常相关
chunk B：非常相关
chunk C：部分相关
chunk D：无关
```

可以定义：

```
3 = highly relevant
2 = relevant
1 = somewhat relevant
0 = irrelevant
```

然后计算：

```
NDCG@5
```

这个指标特别适合：

> 多文档、多证据 RAG。

---

## 二十二、推荐的 Retrieval Metrics

如果你在做一个比较正规的 RAG benchmark，我建议至少：

```
Recall@1
Recall@3
Recall@5
Recall@10

Precision@5
Precision@10

MRR@5
MRR@10

NDCG@5
NDCG@10
```

---

## 二十三、第二大类：Context Evaluation

Retrieval 找到东西之后，还有一个问题：

> 找到的东西到底够不够回答问题？

这和 Retrieval 不完全一样。

例如：

问题：

```
2025年北京住宿标准是多少？
```

找到：

```
2025年差旅制度.pdf
```

但是你只拿到了：

```
第1页
```

而真正的标准在：

```
第8页
```

这就属于：

> Retrieval 看似成功，但 Context 不完整。

---

## 二十四、Context Recall

可以理解为：

> Ground Truth 中需要的信息，有多少被 Retrieval Context 覆盖？

例如标准答案需要三个事实：

```
事实A
事实B
事实C
```

RAG context 里面只有：

```
事实A
事实B
```

那么：

```
Context Recall ≈ 2/3
```

---

## 二十五、Context Precision

这个和 Precision@K 很类似，但更加针对：

> LLM 实际拿到的 Context。

例如：

```
Context 1：非常相关
Context 2：非常相关
Context 3：无关
Context 4：无关
Context 5：无关
```

那么：

```
Context Precision = 2/5
```

---

## 二十六、为什么 Context Precision 非常重要？

因为很多 RAG：

```
Top 20
```

然后全部扔给 LLM。

看起来：

> Recall 很高。

但是：

```
相关信息 3
无关信息 17
```

这可能导致：

- LLM 注意力被干扰
- 出现错误引用
- 混淆不同版本
- 产生 hallucination
- Token 成本增加

所以：

> **RAG 不是召回越多越好。**

---

## 二十七、第三大类：Generation Evaluation

接下来才是：

> LLM 最终回答得好不好？

这里有几个特别重要的指标。

---

## 二十八、Faithfulness

这是 RAG 最核心的指标之一。

它回答：

> **答案里的内容，是不是来自 Context？**

例如 Context：

```
公司规定：
员工每年有10天年假。
```

LLM：

```
员工每年有10天年假，并且最多可以累积3年。
```

如果 Context 没有：

```
最多可以累积3年
```

那么这个回答就存在：

> Unsupported Claim

也就是：

**答案超出了证据。**

---

## 二十九、Faithfulness ≠ Correctness

这是 RAG Evaluation 里非常重要的概念。

例如：

Context：

```
苹果公司总部位于美国。
```

LLM：

```
苹果公司总部位于中国。
```

显然：

```
Correctness = 0
```

同时：

```
Faithfulness = 0
```

---

但另一个情况：

Context：

```
苹果公司总部位于美国。
```

LLM：

```
苹果公司的总部位于美国。
```

那么：

```
Faithfulness = 1
Correctness = 1
```

---

再比如：

Context：

```
苹果公司总部位于美国。
```

LLM：

```
苹果公司是全球最大的科技公司之一。
```

即使这句话在现实世界可能是合理的，但：

```
Context 没有这个信息
```

那么：

```
Faithfulness ↓
```

所以：

> RAG 要求的是“有证据地回答”。

---

## 三十、Answer Correctness

它回答：

> 最终答案本身对不对？

例如：

Ground Truth：

```
住宿标准为800元/天。
```

模型：

```
住宿标准为800元/天。
```

Correctness：

```
1
```

模型：

```
住宿标准为600元/天。
```

Correctness：

```
0
```

---

## 三十一、Answer Relevance

它回答：

> 回答是不是在回答用户的问题？

例如用户：

```
公司的年假是多少？
```

模型：

```
公司成立于2015年，总部位于上海，主要从事……
```

虽然这些信息可能都是真的。

但是：

```
Answer Relevance 很低
```

---

## 三十二、Completeness

有时候答案：

```
不是错
```

但是：

```
没回答完整
```

例如问题：

```
北京、上海、深圳的住宿标准分别是多少？
```

正确：

```
北京：800
上海：800
深圳：700
```

模型：

```
北京：800
上海：800
```

这时候：

```
Correctness 部分成立
Completeness 不够
```

---

## 三十三、Citation Correctness

如果你的 RAG 有引用：

```
根据公司差旅制度，住宿标准为800元/天。[1]
```

那么还需要评价：

> \[1\] 这个引用真的支持这句话吗？

例如：

```
[1] 员工考勤制度
```

显然：

```
Citation Correctness = 0
```

所以企业 RAG 非常建议测：

```
Citation Precision
Citation Recall
Citation Correctness
Citation Completeness
```

---

## 三十四、一个非常实用的 RAG Evaluation 体系

我推荐你最终做成下面这个表：

| Category | Metric | 作用 |
| --- | --- | --- |
| Retrieval | Recall@5 | 能不能找到正确内容 |
| Retrieval | Recall@10 | 更大范围召回能力 |
| Retrieval | Precision@5 | Top5 有多少相关 |
| Retrieval | MRR | 正确结果排名 |
| Retrieval | NDCG | 多相关结果排序 |
| Context | Context Recall | 证据是否完整 |
| Context | Context Precision | Context 是否干净 |
| Generation | Faithfulness | 是否忠于证据 |
| Generation | Answer Correctness | 答案是否正确 |
| Generation | Answer Relevance | 是否回答问题 |
| Generation | Completeness | 是否回答完整 |
| Citation | Citation Correctness | 引用是否支持答案 |
| System | Latency | 延迟 |
| System | Cost | 成本 |

---

## 三十五、然后你就可以真正比较两个 RAG

假设：

## RAG A

```
Recall@5       91%
Precision@5    72%
MRR            0.81

Context Recall 89%
Context Precision 76%

Faithfulness   94%
Answer Correctness 88%
Answer Relevance 93%

Latency        1.2s
Cost           $0.012/query
```

---

## RAG B

```
Recall@5       96%
Precision@5    55%
MRR            0.72

Context Recall 94%
Context Precision 51%

Faithfulness   82%
Answer Correctness 84%
Answer Relevance 90%

Latency        2.4s
Cost           $0.025/query
```

你会发现一个非常典型的现象：

> B 的 Retrieval Recall 更高，但最终 RAG 效果未必更好。

因为：

```
B 找了很多东西
↓
但噪音很多
↓
LLM 被干扰
↓
Faithfulness 下降
↓
最终 Correctness 下降
```

这就是为什么：

> **不能用单一指标评价 RAG。**

---

## 三十六、RAG Evaluation 最好分成三层

我非常推荐这个结构。

```
Level 1
Retrieval Evaluation

Level 2
Generation Evaluation

Level 3
End-to-End Evaluation
```

---

## 三十七、Level 1：Retrieval Benchmark

固定：

```
LLM = GPT/Claude/Qwen/其他
```

固定：

```
Prompt
```

只替换：

```
Embedding
Retriever
Reranker
Chunking
```

例如：

```
Embedding A
Embedding B
Embedding C
```

比较：

```
Recall@5
Recall@10
MRR
NDCG
```

这样你可以知道：

> 到底是哪个 Retriever 好。

---

## 三十八、Level 2：Generation Benchmark

固定：

```
Retriever
```

只替换：

```
LLM
Prompt
Context strategy
```

例如：

```
GPT
Qwen
Claude
Llama
```

比较：

```
Faithfulness
Correctness
Relevance
Completeness
```

这样知道：

> 到底是 LLM 还是 Prompt 的问题。

---

## 三十九、Level 3：End-to-End Benchmark

最后：

```
用户问题
 ↓
完整 RAG
 ↓
最终答案
```

评价：

```
Correctness
Faithfulness
Relevance
Completeness
Citation
Latency
Cost
```

这才是：

> 用户真正感受到的 RAG 质量。

---

## 四十、非常关键：做 Ablation Test

如果你真的想研究：

> “我的 RAG 到底哪里做得好？”

一定要做 Ablation。

比如你的 RAG：

```
Hybrid Search
+
Reranker
+
Query Rewrite
+
Parent Document Retrieval
```

不要一次全开。

你可以测试：

### Experiment 1

```
Vector Search
```

### Experiment 2

```
Vector Search
+
BM25
```

### Experiment 3

```
Vector Search
+
BM25
+
Reranker
```

### Experiment 4

```
Vector Search
+
BM25
+
Reranker
+
Query Rewrite
```

然后：

| Version | Recall@5 | MRR | Faithfulness | Correctness |
| --- | --- | --- | --- | --- |
| Vector | 81% | 0.69 | 84% | 79% |
| +BM25 | 87% | 0.74 | 88% | 84% |
| +Reranker | 91% | 0.82 | 93% | 89% |
| +Rewrite | 93% | 0.85 | 94% | 91% |

这时候你才能知道：

> 哪一个组件真正带来了收益。

---

## 四十一、Chunking 也应该单独测试

这是 RAG 中非常容易被忽略的地方。

例如测试：

```
Chunk 256
Chunk 512
Chunk 1024
Chunk 2048
```

以及：

```
chunk_size
+
overlap
```

例如：

```
256 / overlap 50
512 / overlap 100
1024 / overlap 200
```

分别测：

```
Recall@5
MRR
NDCG
Context Precision
Answer Correctness
```

你可能发现：

```
256:
Recall 85%

512:
Recall 91%

1024:
Recall 93%

2048:
Recall 94%
```

但：

```
Context Precision

256: 91%
512: 88%
1024: 73%
2048: 51%
```

这就说明：

> Chunk 越大不一定越好。

---

## 四十二、Top-K 也要做实验

例如：

```
K = 1
K = 3
K = 5
K = 10
K = 20
```

测：

```
Recall
Precision
Faithfulness
Correctness
Latency
Token Cost
```

你可能得到：

| K | Recall | Precision | Correctness |
| --- | --- | --- | --- |
| 1 | 72% | 92% | 80% |
| 3 | 87% | 86% | 88% |
| 5 | 92% | 78% | 91% |
| 10 | 96% | 61% | 89% |
| 20 | 98% | 42% | 82% |

这就是一个非常典型的：

> **Recall 和 Noise Trade-off**

---

## 四十三、Reranker 也可以这样测

例如：

```
Vector Search Top 50
        ↓
Reranker
        ↓
Top 5
```

测试：

```
没有 Reranker
BGE Reranker
Cohere Reranker
Cross Encoder
其他 Reranker
```

比较：

```
Recall@5
NDCG@5
MRR
Context Precision
Answer Correctness
```

---

## 四十四、不要只测试平均值

这一点特别重要。

假设：

```
RAG A
Average Correctness = 90%

RAG B
Average Correctness = 91%
```

看起来 B 更好。

但是进一步拆：

| Question Type | A | B |
| --- | --- | --- |
| Simple | 95% | 96% |
| Multi-hop | 90% | 84% |
| Long context | 88% | 93% |
| No-answer | 92% | 72% |
| Temporal | 85% | 94% |

这时候你会发现：

> B 并不是全面优于 A。

它只是：

> 某些类型的问题更强。

所以建议做：

```
Overall
+
Per Category
```

---

## 四十五、特别建议测试 Hard Cases

真实生产环境中，最重要的往往不是简单问题。

可以专门建立：

```
Hard Set
```

包括：

```
1. 多跳问题
2. 相似文档
3. 多版本文档
4. 冲突文档
5. 长文档
6. 表格
7. PDF
8. 图片
9. OCR 错误
10. 无答案
11. 模糊问题
12. 拼写错误
13. 同义词
14. 中英文混合
15. 多语言
```

例如：

```
2024版制度：
住宿标准800

2025版制度：
住宿标准900
```

问：

```
2024年的标准是多少？
```

这是非常好的 RAG benchmark。

---

## 四十六、Conflict Test

这个非常重要。

例如：

```
Document A:
住宿标准 800

Document B:
住宿标准 900
```

用户问：

```
2025年住宿标准是多少？
```

好的 RAG 应该能够：

```
识别时间
+
找到正确版本
+
引用正确文档
```

而不是：

```
800 + 900
```

或者：

```
900
```

但引用的是 2024 文档。

---

## 四十七、No-answer Test

这是衡量 RAG 是否会 hallucination 的核心测试。

例如：

知识库：

```
公司总部：
上海
```

用户：

```
公司在东京有几个办公室？
```

正确行为：

```
当前知识库没有找到相关信息，
因此无法确认公司在东京的办公室数量。
```

而不是：

```
公司在东京有2个办公室。
```

你可以定义：

```
Abstention Accuracy
```

例如：

```
100 个无答案问题

正确拒答：
93

Abstention Accuracy = 93%
```

---

## 四十八、LLM-as-a-Judge

现在 RAG Evaluation 很常用的方法之一是：

> 用另一个 LLM 当 Judge。

例如：

```
Question
Context
Answer
Ground Truth
```

交给 Judge：

```
请判断 Answer 是否被 Context 支持。
评分 1~5。
```

例如：

```
Faithfulness:
5 = 完全有证据
4 = 基本有证据
3 = 部分有证据
2 = 有明显 unsupported claim
1 = 大部分内容没有依据
```

---

## 四十九、但 LLM Judge 不能盲信

这是一个非常重要的问题。

因为：

```
Judge LLM
```

本身也可能：

```
判断错误
```

所以最好：

```
LLM Judge
+
Human Evaluation
```

---

## 五十、Human Evaluation 怎么做？

随机抽：

```
100～300 条
```

让人工标注：

```
Correct?
Faithful?
Relevant?
Complete?
Citation correct?
```

例如：

| Question | Correct | Faithful | Complete |
| --- | --- | --- | --- |
| Q1 | 1 | 1 | 1 |
| Q2 | 1 | 0 | 1 |
| Q3 | 0 | 1 | 0 |

然后：

```
LLM Judge
```

和：

```
Human Label
```

做一致性比较。

如果：

```
Human vs Judge Agreement
```

很高：

> 才比较放心使用 LLM Judge 做大规模 Evaluation。

---

## 五十一、推荐一个实际可落地的 Evaluation Pipeline

我建议你直接做成：

```
Evaluation Dataset
                        │
                        ↓
                 ┌─────────────┐
                 │ RAG System  │
                 └──────┬──────┘
                        │
            ┌───────────┴───────────┐
            ↓                       ↓
       Retrieval Log             Final Answer
            │                       │
            ↓                       ↓
     Retrieval Metrics       Generation Metrics
            │                       │
    ┌───────┼───────┐       ┌───────┼───────┐
    ↓       ↓       ↓       ↓       ↓       ↓
Recall    MRR     NDCG    Correct  Faithful Relevant
Precision                 Complete Citation
            │                       │
            └───────────┬───────────┘
                        ↓
                  Final Dashboard
```

---

## 五十二、日志一定要保存

每次 RAG 请求最好保存：

```json
{
  "query": "...",

  "retrieved_documents": [
    {
      "doc_id": "123",
      "chunk_id": "456",
      "score": 0.87,
      "rank": 1
    }
  ],

  "context": "...",

  "answer": "...",

  "latency": 1.28,

  "input_tokens": 3200,

  "output_tokens": 500
}
```

如果有：

```
reranker score
embedding score
BM25 score
```

也保存。

否则以后很难 Debug。

---

## 五十三、Debug 一个错误的 RAG

假设：

```
用户：
2025年上海住宿标准是多少？

RAG：
回答 800 元
```

Ground Truth：

```
900 元
```

不要简单记录：

```
❌ RAG Answer Wrong
```

而应该继续分析：

### Step 1

有没有找到正确文档？

```
2025 Travel Policy
```

如果：

```
没有
```

那么：

> Retrieval Error

---

如果找到了：

```
2025 Travel Policy
```

继续。

---

### Step 2

正确 chunk 有没有进入 Top-K？

如果：

```
没有
```

说明：

> Retrieval / Ranking Error

---

### Step 3

正确 chunk 在 Context 里吗？

如果：

```
有
```

继续。

---

### Step 4

LLM 有没有正确利用？

Context：

```
上海：900
```

LLM：

```
上海：800
```

说明：

> Generation / Reasoning Error

---

### Step 5

如果答案正确，但是引用错了：

> Citation Error

---

## 五十四、这样你就可以统计 Error Breakdown

例如测试：

```
1000 questions
```

错误：

```
Retrieval Error       82
Ranking Error         43
Context Error         25
Generation Error      71
Citation Error        19
No-answer Error       32
```

那么你就知道：

> 你的 RAG 到底应该优化哪里。

这比单纯说：

```
Accuracy = 87%
```

有价值很多。

---

## 五十五、最终可以做一个 RAG Scorecard

例如：

| Dimension | RAG A | RAG B |
| --- | --- | --- |
| Recall@5 | 91% | 94% |
| Precision@5 | 78% | 65% |
| MRR | 0.83 | 0.79 |
| NDCG@10 | 0.88 | 0.86 |
| Context Recall | 90% | 94% |
| Context Precision | 81% | 62% |
| Faithfulness | 95% | 87% |
| Correctness | 91% | 89% |
| Relevance | 94% | 93% |
| Completeness | 88% | 91% |
| Citation Accuracy | 96% | 84% |
| Latency | 1.3s | 2.1s |
| Cost/query | $0.01 | $0.02 |

这种表格非常适合：

> 对比两个 RAG。

---

## 五十六、但是不要简单搞一个“总分”

比如：

```
RAG Score =
0.2 Recall
+ 0.2 Faithfulness
+ 0.3 Correctness
+ ...
```

这个做法要非常谨慎。

因为：

```
业务不同
```

权重就不同。

比如：

### 企业法律 RAG

你可能更关注：

```
Citation
Faithfulness
Correctness
```

### 客服 RAG

可能更关注：

```
Answer Relevance
Correctness
Latency
```

### 医疗知识库

可能更加关注：

```
Faithfulness
Citation
Abstention
Correctness
```

所以不要认为：

> 一个 Universal RAG Score 可以代表所有 RAG。

---

## 五十七、我更推荐 Pareto 思维

比如两个系统：

```
RAG A

Correctness 92%
Latency 1s
Cost $0.01
```
```
RAG B

Correctness 94%
Latency 3s
Cost $0.05
```

这里并不能简单说：

> B 一定更好。

因为这是：

```
Quality
vs
Latency
vs
Cost
```

之间的 trade-off。

生产环境通常要同时看：

```
Quality
Latency
Cost
Reliability
```

---

## 五十八、一个比较成熟的 RAG Benchmark 应该长这样

我给你一个可以直接落地的版本：

## Dataset

```
1000 Questions
```

其中：

```
200 Simple
150 Multi-hop
150 Long-context
100 Temporal
100 Multi-document
100 No-answer
100 Ambiguous
100 Hard Retrieval
```

---

## Retrieval Metrics

```
Recall@1
Recall@3
Recall@5
Recall@10

Precision@5
Precision@10

MRR@5
NDCG@5
NDCG@10
```

---

## Context Metrics

```
Context Recall
Context Precision
Context Relevance
```

---

## Generation Metrics

```
Answer Correctness
Answer Relevance
Faithfulness
Completeness
```

---

## Citation Metrics

```
Citation Precision
Citation Recall
Citation Correctness
Citation Completeness
```

---

## System Metrics

```
P50 latency
P95 latency
P99 latency

Token usage
Cost/query
Error rate
Timeout rate
```

---

## Robustness

```
No-answer
Ambiguous
Typos
Synonyms
Long query
Multi-hop
Conflicting documents
Old/new versions
```

---

## 五十九、如果你是实际做 RAG，我建议优先关注这 8 个

如果你不想一开始搞几十个指标，可以先做：

```
① Recall@5
② MRR@5
③ NDCG@5
④ Context Precision
⑤ Context Recall
⑥ Faithfulness
⑦ Answer Correctness
⑧ Answer Relevance
```

再加：

```
⑨ Citation Correctness
⑩ Abstention Accuracy
```

基本就已经是一个比较完整的 RAG Evaluation 体系了。

---

## 六十、最关键的一点：先定位问题，再优化

最终你可以把 RAG 问题分成：

```
RAG Error
                   │
     ┌─────────────┼─────────────┐
     ↓             ↓             ↓
Retrieval Error  Context Error  Generation Error
     │             │             │
  找不到          不完整          答错
  找错            噪声多          幻觉
  排名错          版本错          漏答
     │             │             │
     ↓             ↓             ↓
 Embedding       Chunking       Prompt
 BM25            Top-K          LLM
 Hybrid          Reranker       Context
 Reranker        Filtering      Generation
```

这才是 RAG Evaluation 真正有价值的地方。

不是最后得到一个：

```
RAG = 87分
```

而是得到：

```
我们的 RAG：

Retrieval Recall：94%
但是：
Context Precision：61%

说明：
召回能力不错，但噪声太多。

进一步发现：
Top 20 → Top 5 的 reranker 效果不好。

于是：
优化 reranker。

优化后：
Context Precision：61% → 79%
Faithfulness：87% → 94%
Answer Correctness：85% → 91%
```

**这种 Evaluation 才真正能够指导 RAG 优化。**

---

## 如果你正在实际开发一个 RAG，我建议采用这个最小闭环

```
① 建测试集
                  ↓
             ② 固定 Ground Truth
                  ↓
       ┌──────────┴──────────┐
       ↓                     ↓
  ③ 测 Retrieval        ④ 测 Generation
       ↓                     ↓
Recall/MRR/NDCG       Correct/Faithful
       │                     │
       └──────────┬──────────┘
                  ↓
             ⑤ Error Analysis
                  ↓
       ┌──────────┼──────────┐
       ↓          ↓          ↓
    Chunking   Retrieval   Reranker
       ↓          ↓          ↓
             ⑥ Ablation
                  ↓
             ⑦ 再测试
                  ↓
             ⑧ Regression
                  ↓
            Production
```

尤其是最后一个 **Regression Test** 很重要：以后你换 Embedding、换 Reranker、换 Chunk Size、换 LLM，都自动跑一遍测试集，防止“优化了 A，结果把 B 搞坏了”。

如果你愿意，我下一步可以直接给你一套 **可运行的 RAG Evaluation 代码框架** ，包括 **Python + RAGAS/DeepEval + Recall@K/MRR/NDCG + LLM Judge + 自动生成 Excel 评测报告** ，你把自己的 RAG 接进去就能直接比较两个 RAG。