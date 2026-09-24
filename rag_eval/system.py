"""系统层指标：延迟分位数、Token、成本、错误率。全确定性。

延迟单位毫秒（run_log.latency_ms），成本美元（cost_usd 或由 tokens 按价目表折算）。
"""
from __future__ import annotations

from typing import Iterable

# 主办方统一价目表（USD / 1M tokens）。参赛方没填 cost_usd 时按这个折算，保证可比。
DEFAULT_PRICE = {
    "input": 0.5,
    "output": 2.0,
}


def percentile(values: list[float], p: float) -> float | None:
    """线性插值分位数，p ∈ [0, 100]。空列表返回 None。"""
    if not values:
        return None
    xs = sorted(values)
    if len(xs) == 1:
        return float(xs[0])
    rank = (p / 100) * (len(xs) - 1)
    lo = int(rank)
    hi = min(lo + 1, len(xs) - 1)
    frac = rank - lo
    return float(xs[lo] + (xs[hi] - xs[lo]) * frac)


def is_timeout(rec: dict) -> bool:
    err = (rec.get("error") or "").lower()
    return "timeout" in err or "timed out" in err or "超时" in err


def is_failed(rec: dict) -> bool:
    """超时/异常的题。质量指标不计，但计入 error rate。"""
    return bool(rec.get("error"))


def record_cost_usd(rec: dict, price: dict[str, float] | None = None) -> float | None:
    """优先用参赛方自报 cost_usd；否则按统一价目表从 tokens 折算。"""
    if rec.get("cost_usd") is not None:
        return float(rec["cost_usd"])
    tin, tout = rec.get("input_tokens"), rec.get("output_tokens")
    if tin is None and tout is None:
        return None
    p = price or DEFAULT_PRICE
    return ((tin or 0) * p["input"] + (tout or 0) * p["output"]) / 1_000_000


def system_metrics(
    records: Iterable[dict],
    price: dict[str, float] | None = None,
) -> dict:
    """整场 run 的系统层指标。records 为一个系统的所有 run_log 记录。"""
    recs = list(records)
    n = len(recs)
    failed = [r for r in recs if is_failed(r)]
    timeouts = [r for r in failed if is_timeout(r)]

    latencies = [float(r["latency_ms"]) for r in recs if r.get("latency_ms") is not None]
    in_toks = [float(r["input_tokens"]) for r in recs if r.get("input_tokens") is not None]
    out_toks = [float(r["output_tokens"]) for r in recs if r.get("output_tokens") is not None]
    costs = [c for r in recs if (c := record_cost_usd(r, price)) is not None]

    return {
        "n_questions": n,
        "n_error": len(failed),
        "n_timeout": len(timeouts),
        "error_rate": len(failed) / n if n else 0.0,
        "timeout_rate": len(timeouts) / n if n else 0.0,
        "latency_p50_ms": percentile(latencies, 50),
        "latency_p95_ms": percentile(latencies, 95),
        "latency_p99_ms": percentile(latencies, 99),
        "latency_mean_ms": sum(latencies) / len(latencies) if latencies else None,
        "input_tokens_mean": sum(in_toks) / len(in_toks) if in_toks else None,
        "output_tokens_mean": sum(out_toks) / len(out_toks) if out_toks else None,
        "cost_per_query_usd": sum(costs) / len(costs) if costs else None,
        "cost_total_usd": sum(costs) if costs else None,
    }
