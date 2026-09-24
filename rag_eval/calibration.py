"""Judge 校准：LLM 判分 vs 人工标注的一致性（《检测RAG质量.md》§50）。

Judge 不能盲信。放大到全量前，先抽 100~300 条人工标注，算一致率与 Cohen's κ：
    κ >= 0.6   可放量使用
    κ <  0.6   改 rubric 重测，不达标不放量

二值化口径（judge.to_binary）：score >= 4 判为达标(1)。
人工侧对应 human_labels 的 correct / faithful / complete（0/1）。
"""
from __future__ import annotations

# metric -> human_labels 字段。只有这 3 个指标有人工标注可对齐。
CALIBRATION_MAP = {
    "correctness": "correct",
    "faithfulness": "faithful",
    "completeness": "complete",
}

KAPPA_GATE = 0.6


def agreement_rate(a: list[int], b: list[int]) -> float:
    if not a:
        return 0.0
    return sum(1 for x, y in zip(a, b) if x == y) / len(a)


def confusion_matrix(a: list[int], b: list[int]) -> dict:
    """以 b（人工）为真值：{tp, tn, fp, fn}。fp = Judge 说好但人工说差。"""
    tp = sum(1 for x, y in zip(a, b) if x == 1 and y == 1)
    tn = sum(1 for x, y in zip(a, b) if x == 0 and y == 0)
    fp = sum(1 for x, y in zip(a, b) if x == 1 and y == 0)
    fn = sum(1 for x, y in zip(a, b) if x == 0 and y == 1)
    return {"tp": tp, "tn": tn, "fp": fp, "fn": fn}


def cohens_kappa(a: list[int], b: list[int]) -> float | None:
    """Cohen's κ = (po - pe) / (1 - pe)。样本太少或退化情况返回 None。"""
    n = len(a)
    if n < 2:
        return None
    po = agreement_rate(a, b)
    labels = set(a) | set(b)
    pe = 0.0
    for c in labels:
        pa = sum(1 for x in a if x == c) / n
        pb = sum(1 for x in b if x == c) / n
        pe += pa * pb
    if abs(1 - pe) < 1e-9:
        return 1.0 if po >= 1 - 1e-9 else 0.0
    return (po - pe) / (1 - pe)


def calibrate(
    judge_binary: dict[tuple[str, str, str], int],
    human_labels: list[dict],
    gate: float = KAPPA_GATE,
) -> dict:
    """judge_binary: {(question_id, system_name, metric): 0|1}
    human_labels: human_labels.jsonl 的记录列表。
    """
    per_metric: dict[str, dict] = {}
    for metric, field in CALIBRATION_MAP.items():
        ja: list[int] = []
        hb: list[int] = []
        for rec in human_labels:
            if rec.get(field) is None:
                continue
            key = (rec.get("question_id"), rec.get("system_name"), metric)
            if key not in judge_binary:
                continue
            ja.append(judge_binary[key])
            hb.append(int(rec[field]))
        kappa = cohens_kappa(ja, hb)
        per_metric[metric] = {
            "human_field": field,
            "n_paired": len(ja),
            "agreement_rate": agreement_rate(ja, hb) if ja else None,
            "cohens_kappa": kappa,
            "confusion": confusion_matrix(ja, hb) if ja else None,
            "pass": (kappa is not None and kappa >= gate),
        }

    kappas = [m["cohens_kappa"] for m in per_metric.values() if m["cohens_kappa"] is not None]
    return {
        "gate": gate,
        "per_metric": per_metric,
        "kappa_mean": sum(kappas) / len(kappas) if kappas else None,
        "n_paired_total": sum(m["n_paired"] for m in per_metric.values()),
        "pass": bool(kappas) and all(
            m["pass"] for m in per_metric.values() if m["n_paired"] > 0
        ),
        "verdict": (
            "κ 达标，可放量使用 Judge"
            if kappas and all(m["pass"] for m in per_metric.values() if m["n_paired"] > 0)
            else "κ 未达标或样本不足，改 rubric 后重测，暂不放量"
        ),
    }


def to_judge_binary(records_scores: list[dict]) -> dict[tuple[str, str, str], int]:
    """judge_metric 输出 -> 二值标签，键与 human_labels 对齐。"""
    from .judge import to_binary

    out: dict[tuple[str, str, str], int] = {}
    for row in records_scores:
        for metric in CALIBRATION_MAP:
            res = row.get("scores", {}).get(metric)
            if res and res.get("score") is not None:
                out[(row["question_id"], row["system_name"], metric)] = to_binary(res["score"])
    return out
