"""检索层确定性指标：Hit@K / Recall@K / Precision@K / MRR@K / NDCG@K。

不调任何 LLM。输入是单条 run_log 记录 + 对应 ground truth，输出该题各项分数。

术语对齐《检测RAG质量.md》：
- Hit@K      §14 的「Recall@K = 成功找到的问题数 / 总问题数」，即任意命中即 1
- Recall@K   chunk 级召回：命中的相关 chunk 数 / 相关 chunk 总数（多跳题更敏感）
- Precision@K §17：Top-K 里有多少真的有用
- MRR@K      §19：第一个正确结果排在第几位
- NDCG@K     §21：多相关结果 + 分级相关度的排序质量

scorable 判定（返回 None 表示本题不计该项，聚合时跳过）：
- ground truth 无 chunk（无答案题）      → 检索指标无定义，走 Abstention
- 记录没给 retrieved_chunks 字段          → N/A，不计 0 分（契约 §2.2）
- 记录 error 非空（超时/异常）            → 计入 error rate，不污染质量指标
- 其余（含 retrieved_chunks 为空列表）    → 照常计分，空列表即全 0
"""
from __future__ import annotations

import math

DEFAULT_KS = (1, 3, 5, 10)

# relevance 上界（schema 里是 0-3），NDCG 增益 2^rel - 1 → 0/1/3/7
MAX_RELEVANCE = 3


def gt_relevance_map(gt_chunks: list[dict]) -> dict[str, int]:
    """{chunk_id: relevance}。gt 里重复 chunk_id 取最大 relevance。"""
    out: dict[str, int] = {}
    for c in gt_chunks or []:
        cid = c.get("chunk_id")
        rel = int(c.get("relevance", 3))
        if cid is not None:
            out[cid] = max(out.get(cid, 0), rel)
    return out


def retrieved_ids(rec: dict) -> list[str] | None:
    """按 rank 排序后的 chunk_id 列表；字段缺失返回 None。"""
    if "retrieved_chunks" not in rec or rec["retrieved_chunks"] is None:
        return None
    chunks = sorted(rec["retrieved_chunks"], key=lambda c: c.get("rank", 0))
    return [c.get("chunk_id") for c in chunks]


def is_scorable(rec: dict, gt_map: dict[str, int]) -> bool:
    if not gt_map:                 # 无答案题：检索指标无定义
        return False
    if retrieved_ids(rec) is None:  # 未提交检索结果：N/A
        return False
    if rec.get("error"):            # 超时/异常：走 error rate
        return False
    return True


# --------------------------------------------------------------- 单题指标

def hit_at_k(ids: list[str], gt_map: dict[str, int], k: int) -> int:
    """Top-K 内是否命中任一相关 chunk：0/1。"""
    relevant = {cid for cid, rel in gt_map.items() if rel >= 1}
    return int(bool(set(ids[:k]) & relevant))


def recall_at_k(ids: list[str], gt_map: dict[str, int], k: int) -> float:
    """chunk 级召回：Top-K 命中的相关 chunk 数 / 相关 chunk 总数。"""
    relevant = {cid for cid, rel in gt_map.items() if rel >= 1}
    if not relevant:
        return 0.0
    return len(set(ids[:k]) & relevant) / len(relevant)


def precision_at_k(ids: list[str], gt_map: dict[str, int], k: int) -> float:
    """Top-K 精度：命中数 / K。分母固定取 K（§17），返回不足 K 条也要被扣。"""
    if k <= 0:
        return 0.0
    top = ids[:k]
    relevant = {cid for cid, rel in gt_map.items() if rel >= 1}
    return len(set(top) & relevant) / k


def mrr_at_k(ids: list[str], gt_map: dict[str, int], k: int) -> float:
    """倒数排名：第一个相关结果的 1/rank，未命中为 0。"""
    relevant = {cid for cid, rel in gt_map.items() if rel >= 1}
    for i, cid in enumerate(ids[:k], 1):
        if cid in relevant:
            return 1.0 / i
    return 0.0


def dcg_at_k(gains: list[float], k: int) -> float:
    """DCG = Σ gain_i / log2(i+1)，i 从 1 起。"""
    total = 0.0
    for i, g in enumerate(gains[:k], 1):
        total += g / math.log2(i + 1)
    return total


def ndcg_at_k(ids: list[str], gt_map: dict[str, int], k: int) -> float:
    """NDCG：增益 2^rel - 1，IDCG 用 gt relevance 降序的理想排序。"""
    gains = [(2 ** min(gt_map.get(cid, 0), MAX_RELEVANCE) - 1) for cid in ids]
    ideal = sorted(
        (2 ** min(rel, MAX_RELEVANCE) - 1 for rel in gt_map.values()),
        reverse=True,
    )
    idcg = dcg_at_k(ideal, k)
    if idcg <= 0:
        return 0.0
    return dcg_at_k(gains, k) / idcg


# ---------------------------------------------------------------- 汇总

def retrieval_metrics(
    rec: dict,
    gt_chunks: list[dict],
    ks: tuple[int, ...] = DEFAULT_KS,
) -> dict[str, float] | None:
    """单条记录的检索层指标。不可计分时返回 None。"""
    gt_map = gt_relevance_map(gt_chunks)
    if not is_scorable(rec, gt_map):
        return None
    ids = retrieved_ids(rec) or []

    out: dict[str, float] = {}
    for k in ks:
        out[f"hit@{k}"] = float(hit_at_k(ids, gt_map, k))
        out[f"recall@{k}"] = recall_at_k(ids, gt_map, k)
        out[f"precision@{k}"] = precision_at_k(ids, gt_map, k)
        out[f"mrr@{k}"] = mrr_at_k(ids, gt_map, k)
        out[f"ndcg@{k}"] = ndcg_at_k(ids, gt_map, k)
    out["retrieved_count"] = float(len(ids))
    return out
