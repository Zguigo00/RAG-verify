"""聚合：算均值、按题型分组、Pareto 前沿。

对应《检测RAG质量.md》两处硬要求：
- §44「不要只测平均值」  → by_category 按题型拆开
- §56/§57「不要迷信总分」→ pareto_front 用 质量 vs 延迟 vs 成本 的支配关系，而非加权求和
"""
from __future__ import annotations

from typing import Callable, Iterable

from .retrieval import DEFAULT_KS, retrieval_metrics
from .system import system_metrics
from .triage import approx_correct, error_breakdown, triage, triage_all


def mean(values: Iterable[float | None]) -> float | None:
    xs = [float(v) for v in values if v is not None]
    return sum(xs) / len(xs) if xs else None


def mean_dict(dicts: list[dict]) -> dict[str, float | None]:
    """逐 key 求均值，跳过 None（缺字段不拉低分数，契约 §2.2）。"""
    keys = sorted({k for d in dicts for k in d})
    return {k: mean(d.get(k) for d in dicts) for k in keys}


# ------------------------------------------------------------------ 单系统

def per_question(
    records: list[dict],
    gt_by_id: dict[str, dict],
    correctness: dict[tuple[str, str], bool] | None = None,
    ks: tuple[int, ...] = DEFAULT_KS,
) -> list[dict]:
    """逐题明细：检索指标 + 归因 + 正确性。Dashboard 逐题下钻用这份。"""
    correctness = correctness or {}
    rows = []
    for rec in records:
        gt = gt_by_id.get(rec.get("question_id"))
        if gt is None:
            continue
        key = (rec.get("question_id"), rec.get("system_name"))
        is_correct = correctness.get(key, approx_correct(rec, gt))
        rows.append(
            {
                "question_id": rec["question_id"],
                "category": gt.get("category"),
                "is_correct": is_correct,
                "retrieval": retrieval_metrics(rec, gt.get("ground_truth_chunks") or [], ks),
                "triage": triage(rec, gt, is_correct=is_correct),
            }
        )
    return rows


def build_results(
    records: list[dict],
    gt_by_id: dict[str, dict],
    correctness: dict[tuple[str, str], bool] | None = None,
    price: dict[str, float] | None = None,
    ks: tuple[int, ...] = DEFAULT_KS,
) -> dict:
    """单个系统的完整评测结果。"""
    records = list(records)
    rows = per_question(records, gt_by_id, correctness, ks)
    name = records[0].get("system_name", "?") if records else "?"

    # 检索层均值：只在可计分的题上求均值（无答案题/缺字段/超时自动排除）
    ret_rows = [r["retrieval"] for r in rows if r["retrieval"] is not None]

    # 按题型分组（§44）
    by_cat: dict[str, list[dict]] = {}
    for r in rows:
        by_cat.setdefault(r.get("category") or "?", []).append(r)
    by_category = {}
    for cat, rs in sorted(by_cat.items()):
        by_category[cat] = {
            "n": len(rs),
            "correct_rate": mean(1.0 if r["is_correct"] else 0.0 for r in rs),
            "retrieval": mean_dict([r["retrieval"] for r in rs if r["retrieval"] is not None]),
        }

    judged = [r for r in rows if r["is_correct"] is not None]
    return {
        "system_name": name,
        "n_questions": len(records),
        "n_judged": len(judged),
        "correct_rate": mean(1.0 if r["is_correct"] else 0.0 for r in judged),
        "retrieval": mean_dict(ret_rows),
        "by_category": by_category,
        "system": system_metrics(records, price),
        "error_breakdown": error_breakdown([r["triage"] for r in rows]),
        "per_question": rows,
    }


def results_for_all(
    records: list[dict],
    gt_by_id: dict[str, dict],
    correctness: dict[tuple[str, str], bool] | None = None,
    price: dict[str, float] | None = None,
    ks: tuple[int, ...] = DEFAULT_KS,
) -> dict[str, dict]:
    """按 system_name 分组跑 build_results。"""
    by_sys: dict[str, list[dict]] = {}
    for rec in records:
        by_sys.setdefault(rec.get("system_name", "?"), []).append(rec)
    out = {
        name: build_results(recs, gt_by_id, correctness, price, ks)
        for name, recs in sorted(by_sys.items())
    }
    for name, res in out.items():
        res["pareto"] = None  # 由 pareto_front 回填
    return out


# ------------------------------------------------------------------ Pareto

def pareto_front(
    points: dict[str, dict],
    quality_key: str = "correct_rate",
) -> list[str]:
    """非支配解集。

    quality 越大越好，latency / cost 越小越好。A 支配 B = 三项都不差且至少一项更好。
    §57：A 质量高但慢、B 质量略高但贵 → 两者都在前沿上，不能简单说谁赢。
    """
    items = []
    for name, res in points.items():
        q = res.get(quality_key)
        lat = (res.get("system") or {}).get("latency_p95_ms")
        cost = (res.get("system") or {}).get("cost_per_query_usd")
        if q is None:
            continue
        items.append((name, q, lat if lat is not None else float("inf"),
                      cost if cost is not None else float("inf")))

    front = []
    for name, q, lat, cost in items:
        dominated = False
        for name2, q2, lat2, cost2 in items:
            if name2 == name:
                continue
            no_worse = (q2 >= q) and (lat2 <= lat) and (cost2 <= cost)
            strictly = (q2 > q) or (lat2 < lat) or (cost2 < cost)
            if no_worse and strictly:
                dominated = True
                break
        if not dominated:
            front.append(name)

    for name in points:
        points[name]["pareto"] = name in front
    return front
