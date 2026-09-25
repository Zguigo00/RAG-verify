"""一致性审计：不看答案对不对，只看「答题卡的数据自不自洽」。

原理：真跑出来的中间过程会留下物理约束的痕迹，伪造的留不下。
这些约束不需要知道标准答案就能验证，所以能当反作弊抓手。

检测到的是**可疑信号**，不是作弊定罪 —— 每条都给出可能的正常解释，需人工复核。

信号分级：
  high   物理上不可能或分布严重退化，几乎只能是伪造
  medium 明显不自洽，也可能来自非常规实现
  low    内部排序不一致，通常可解释（如 rank 由 reranker 决定而 score 是向量相似度）
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# 阈值刻意保守，宁可漏报也不要冤枉正常实现
THRESHOLDS = {
    # context 很长但 input_tokens 极小 -> context 根本没送进 LLM
    # 各家 tokenizer 中文约 0.5~2 字/词元，比值 > 15 已远超任何 tokenizer
    "chars_per_token": 15,
    # 耗时极短却声称送了上千 token -> LLM 不可能这么快
    "min_latency_ms": 100,
    "tokens_for_latency": 1000,
    # 分阶段耗时之和不该超过端到端耗时
    "trace_ratio": 1.05,
}


def _norm(s: str) -> str:
    return "".join((s or "").split())


def audit_record(rec: dict) -> list[dict]:
    """单条记录的可疑信号。返回 [{level, signal, detail}]。"""
    out: list[dict] = []

    def add(level: str, signal: str, detail: str) -> None:
        out.append({"level": level, "signal": signal, "detail": detail})

    chunks = rec.get("retrieved_chunks") or []
    scores = [c.get("score") for c in chunks if c.get("score") is not None]

    # --- score 分布退化：真实检索是连续分布 ---
    if len(scores) >= 3 and len(set(scores)) == 1:
        add("high", "score_constant",
            f"{len(scores)} 个 chunk 的 score 全部为 {scores[0]}（真实检索应为连续分布）")
    if len(scores) >= 3 and all(s in (0, 1, 0.0, 1.0) for s in scores):
        add("medium", "score_binary", f"score 只取 0/1，疑似占位值")

    # --- score 与 rank 排序不一致 ---
    if len(scores) >= 2:
        asc = sum(1 for i in range(1, len(scores)) if scores[i] > scores[i - 1])
        if asc and asc / (len(scores) - 1) > 0.5:
            add("low", "score_rank_inconsistent",
                f"score 随 rank 上升的比例 {asc}/{len(scores) - 1}，与最终排序不一致"
                f"（若 rank 由 reranker 决定而 score 是向量相似度，属正常，可在 debug 里注明）")

    # --- context 与 input_tokens 严重不符 ---
    ctx = rec.get("context") or ""
    tin = rec.get("input_tokens")
    if ctx and isinstance(tin, (int, float)) and tin > 0:
        ratio = len(ctx) / tin
        if len(ctx) >= 200 and ratio > THRESHOLDS["chars_per_token"]:
            add("high", "token_context_mismatch",
                f"context {len(ctx)} 字符但 input_tokens 仅 {tin}（{ratio:.1f} 字/词元，"
                f"远超任何 tokenizer）。context 疑似未真正送入 LLM")
        if tin > len(ctx) * 2 and len(ctx) >= 50:
            add("medium", "context_understated",
                f"input_tokens {tin} 明显大于 context {len(ctx)} 字符，context 可能填得不完整")

    # --- 耗时与 token 数不匹配 ---
    lat = rec.get("latency_ms")
    if isinstance(lat, (int, float)) and isinstance(tin, (int, float)):
        if lat < THRESHOLDS["min_latency_ms"] and tin > THRESHOLDS["tokens_for_latency"]:
            add("high", "latency_impossible",
                f"input_tokens {tin} 却只用 {lat}ms，含 LLM 调用的端到端耗时不可能这么短")

    # --- trace 各段之和超过端到端 ---
    tr = rec.get("trace") or {}
    if isinstance(lat, (int, float)) and lat > 0 and tr:
        vals = [v for v in tr.values() if isinstance(v, (int, float))]
        total = sum(vals)
        if vals and total > lat * THRESHOLDS["trace_ratio"]:
            add("medium", "trace_over_total",
                f"trace 各段之和 {total:.0f}ms > latency_ms {lat}ms，数据不自洽")

    # --- claim 应是答案原句 ---
    answer = _norm(rec.get("answer") or "")
    for i, c in enumerate(rec.get("citations") or [], 1):
        claim = _norm(c.get("claim") or "")
        if claim and answer and claim not in answer:
            add("medium", "claim_not_in_answer",
                f"citations[{i}] 的 claim 不在 answer 原文中（规则要求写答案原句，"
                f"倒着配引用会被识破）")

    if rec.get("error"):
        return out
    return out


def audit_records(records: list[dict]) -> dict:
    """整场审计。返回按系统聚合的可疑信号。"""
    by_sys: dict[str, list[dict]] = {}
    for r in records:
        by_sys.setdefault(r.get("system_name", "?"), []).append(r)

    out: dict[str, dict] = {}
    for name, recs in sorted(by_sys.items()):
        lats = [r["latency_ms"] for r in recs if isinstance(r.get("latency_ms"), (int, float))]
        per_record = []
        counts: dict[str, int] = {}
        levels: dict[str, int] = {"high": 0, "medium": 0, "low": 0}
        for r in recs:
            sigs = audit_record(r)
            if sigs:
                per_record.append({"question_id": r.get("question_id"), "signals": sigs})
            for s in sigs:
                counts[s["signal"]] = counts.get(s["signal"], 0) + 1
                levels[s["level"]] += 1

        # 耗时分布退化：真实系统是连续分布
        if len(lats) >= 5 and len(set(lats)) <= 2:
            counts["latency_degenerate"] = counts.get("latency_degenerate", 0) + 1
            levels["high"] += 1
            per_record.append({"question_id": "(全量)",
                               "signals": [{"level": "high", "signal": "latency_degenerate",
                                            "detail": f"{len(lats)} 题的 latency_ms 只有 {len(set(lats))} 个不同取值"
                                                      f"{sorted(set(lats))[:5]}，真实耗时应为连续分布"}]})

        risk = "high" if levels["high"] else ("medium" if levels["medium"] else ("low" if levels["low"] else "clean"))
        out[name] = {
            "n_records": len(recs),
            "risk": risk,
            "levels": levels,
            "signals": counts,
            "flagged_records": len(per_record),
            "details": per_record,
        }
    return out
