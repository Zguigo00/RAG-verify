"""提交文件校验器：结构校验（对齐 schemas/）+ 跨行一致性 + 覆盖率统计。

参赛方本地自查：  python -m rag_eval.cli validate --dataset dataset.jsonl --run-log run_log.jsonl
主办方收卷复跑：  同上，另加 --human-labels human_labels.jsonl

校验通过是入库/评测的前置条件。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
SCHEMA_DIR = ROOT / "schemas"
SCHEMA_FILES = {
    "dataset": SCHEMA_DIR / "dataset.schema.json",
    "dataset_public": SCHEMA_DIR / "dataset_public.schema.json",
    "run_log": SCHEMA_DIR / "run_log.schema.json",
    "human_labels": SCHEMA_DIR / "human_labels.schema.json",
}

# 各指标层对应的 run_log 字段。字段缺失 -> 该层显示 N/A，不计 0 分（方案 §2.2）
LAYER_KEYS = [
    ("检索层 Recall@K/Precision@K/MRR/NDCG", "retrieved_chunks"),
    ("上下文层 Context Recall/Precision + Faithfulness", "context"),
    ("生成层 Correctness/Relevance/Completeness", "__answer__"),
    ("引用层 Citation 系列", "citations"),
    ("系统层 延迟/Token/成本/错误率", "__system__"),
]


# ---------------------------------------------------------------- JSONL IO

def load_jsonl(path: Path) -> tuple[list[tuple[int, dict]], list[str]]:
    """读 JSONL，返回 ([(行号, 记录)], 错误列表)。空行跳过，解析错误带行号。"""
    records: list[tuple[int, dict]] = []
    errors: list[str] = []
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return [], [f"{path}: 文件不存在"]
    except OSError as e:
        return [], [f"{path}: 读取失败 {e}"]

    for line_no, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as e:
            errors.append(f"{path.name}:{line_no}  JSON 解析失败: {e}")
            continue
        if not isinstance(obj, dict):
            errors.append(
                f"{path.name}:{line_no}  每行必须是一个 JSON 对象，实际是 {type(obj).__name__}"
            )
            continue
        records.append((line_no, obj))
    return records, errors


# ------------------------------------------------------------ schema 校验

def _load_validator(kind: str):
    try:
        import jsonschema
    except ImportError:  # pragma: no cover
        raise SystemExit(
            "缺少依赖 jsonschema，请先执行: pip install -r requirements.txt"
        )
    schema = json.loads(SCHEMA_FILES[kind].read_text(encoding="utf-8"))
    validator_cls = jsonschema.validators.validator_for(schema)
    validator_cls.check_schema(schema)
    return validator_cls(schema)


def schema_errors(kind: str, items: list[tuple[int, dict]]) -> list[str]:
    """逐条跑 JSON Schema，错误信息带行号 + 字段路径。

    kind="dataset" 时按内容自动选 schema：
      含 ground_truth_answer -> dataset.schema.json（完整版，主办方持有）
      不含                  -> dataset_public.schema.json（公开版，发给参赛方）
    """
    if not items:
        return []
    if kind == "dataset":
        has_gt = any("ground_truth_answer" in rec for _, rec in items)
        kind = "dataset" if has_gt else "dataset_public"
    validator = _load_validator(kind)
    out: list[str] = []
    for line_no, rec in items:
        for err in validator.iter_errors(rec):
            path = "/".join(str(p) for p in err.absolute_path) or "(根)"
            out.append(f"{kind}.jsonl:{line_no}  字段 `{path}`: {err.message}")
    return out


# --------------------------------------------------------- 跨行一致性校验

def load_domains() -> dict[str, dict]:
    """corpus/domains.json 的行业注册表。补行业只改这个文件，schema 不动。"""
    p = ROOT / "corpus" / "domains.json"
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding="utf-8")).get("domains", {})


def check_dataset(items: list[tuple[int, dict]]) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warns: list[str] = []
    seen: dict[str, int] = {}
    registry = load_domains()

    for line_no, rec in items:
        qid = rec.get("question_id")
        if qid in seen:
            errors.append(
                f"dataset:{line_no}  question_id `{qid}` 与第 {seen[qid]} 行重复"
            )
        else:
            seen[qid] = line_no

        domain = rec.get("domain")
        if registry and domain not in registry:
            warns.append(
                f"dataset:{line_no}  domain `{domain}` 未在 corpus/domains.json 注册，"
                f"Dashboard 的行业分组会归到「未注册」"
            )
        elif registry and registry.get(domain, {}).get("status") != "active":
            warns.append(
                f"dataset:{line_no}  domain `{domain}` 状态为 "
                f"{registry.get(domain, {}).get('status')}，尚无 corpus/{domain}/ 语料"
            )

        # schema 的 if/then 已覆盖，这里给更清楚的中文提示
        if rec.get("expected_abstain") and rec.get("ground_truth_chunks"):
            errors.append(
                f"dataset:{line_no}  expected_abstain=true 时 ground_truth_chunks 必须为空"
            )
        if rec.get("category") == "no_answer" and not rec.get("expected_abstain"):
            errors.append(
                f"dataset:{line_no}  category=no_answer 时 expected_abstain 必须为 true"
            )
        if rec.get("expected_abstain") and rec.get("ground_truth_facts"):
            warns.append(f"dataset:{line_no}  无答案题通常不应有 ground_truth_facts")

        chunk_ids = [c.get("chunk_id") for c in rec.get("ground_truth_chunks", [])]
        if len(chunk_ids) != len(set(chunk_ids)):
            errors.append(f"dataset:{line_no}  ground_truth_chunks 内 chunk_id 重复")

    return errors, warns


def check_run_log(
    items: list[tuple[int, dict]],
    dataset_items: list[tuple[int, dict]] | None = None,
) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warns: list[str] = []
    if not items:
        return errors, warns

    systems = {rec.get("system_name") for _, rec in items}
    if len(systems) > 1:
        errors.append(
            "run_log  内 system_name 不一致: "
            + ", ".join(sorted(str(s) for s in systems))
            + "（一份文件只能属于一个系统，请拆分提交）"
        )

    gt_absent = {
        rec["question_id"] for _, rec in (dataset_items or []) if rec.get("expected_abstain")
    }
    gt_ids = {rec.get("question_id") for _, rec in (dataset_items or [])}

    seen_pairs: dict[tuple, int] = {}
    for line_no, rec in items:
        key = (rec.get("system_name"), rec.get("question_id"))
        if key in seen_pairs:
            errors.append(
                f"run_log:{line_no}  ({key[0]}, {key[1]}) 与第 {seen_pairs[key]} 行重复"
            )
        else:
            seen_pairs[key] = line_no

        qid = rec.get("question_id")
        if dataset_items is not None and qid not in gt_ids:
            errors.append(f"run_log:{line_no}  question_id `{qid}` 不在 dataset 中")

        chunks = rec.get("retrieved_chunks") or []
        ranks = [c.get("rank") for c in chunks]
        if ranks and sorted(ranks) != list(range(1, len(chunks) + 1)):
            errors.append(
                f"run_log:{line_no}  retrieved_chunks 的 rank 必须是从 1 开始的连续不重复整数，"
                f"实际 {ranks}"
            )

        # 超时/异常：answer 应为空串并填 error
        if rec.get("error") and rec.get("answer"):
            warns.append(
                f"run_log:{line_no}  已填 error 但 answer 非空，error 记录的题不会计入质量指标"
            )
        if not rec.get("error") and not rec.get("answer"):
            warns.append(f"run_log:{line_no}  answer 为空且未填 error，将被视为漏答")

        if qid in gt_absent and rec.get("answer") and not rec.get("abstained"):
            warns.append(
                f"run_log:{line_no}  该题为无答案题却给出了实质回答且 abstained=false，"
                f"将计为 No-answer Error（幻觉）"
            )

    return errors, warns


def check_human_labels(
    items: list[tuple[int, dict]],
    dataset_items: list[tuple[int, dict]] | None = None,
    run_items: list[tuple[int, dict]] | None = None,
) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warns: list[str] = []
    gt_ids = {rec.get("question_id") for _, rec in (dataset_items or [])}
    run_pairs = {
        (rec.get("question_id"), rec.get("system_name")) for _, rec in (run_items or [])
    }

    seen: dict[tuple, int] = {}
    for line_no, rec in items:
        key = (rec.get("question_id"), rec.get("system_name"), rec.get("labeler"))
        if key in seen:
            errors.append(
                f"human_labels:{line_no}  ({key[0]}, {key[1]}, {key[2]}) "
                f"与第 {seen[key]} 行重复标注"
            )
        else:
            seen[key] = line_no

        if dataset_items is not None and rec.get("question_id") not in gt_ids:
            errors.append(
                f"human_labels:{line_no}  question_id `{rec.get('question_id')}` 不在 dataset 中"
            )
        if run_items is not None:
            pair = (rec.get("question_id"), rec.get("system_name"))
            if pair not in run_pairs:
                errors.append(
                    f"human_labels:{line_no}  {pair} 在 run_log 中不存在，无法复核"
                )

    return errors, warns


# ---------------------------------------------------------------- 覆盖率

def _layer_flags(rec: dict) -> dict[str, bool]:
    return {
        "检索层": bool(rec.get("retrieved_chunks")),
        "上下文层": bool(rec.get("context")),
        "生成层": True,  # answer 必填
        "引用层": bool(rec.get("citations")),
        "系统层": rec.get("latency_ms") is not None
        or rec.get("input_tokens") is not None
        or rec.get("cost_usd") is not None,
    }


def coverage_report(items: list[tuple[int, dict]]) -> dict[str, dict[str, Any]]:
    """按系统统计各指标层字段覆盖率，决定能算哪些指标、算不了的显示 N/A。"""
    if not items:
        return {}
    by_system: dict[str, list[dict]] = {}
    for _, rec in items:
        by_system.setdefault(rec.get("system_name", "?"), []).append(rec)

    out: dict[str, dict[str, Any]] = {}
    for system, recs in sorted(by_system.items()):
        n = len(recs)
        layers = {}
        for label, _ in LAYER_KEYS:
            key = label.split(" ")[0]
            hit = sum(1 for r in recs if _layer_flags(r)[key])
            layers[key] = {
                "label": label,
                "covered": hit,
                "total": n,
                "pct": round(100 * hit / n, 1) if n else 0.0,
                "computable": hit > 0,
            }
        out[system] = {"n_questions": n, "layers": layers}
    return out


# ---------------------------------------------------------------- 汇总入口

def validate_files(
    dataset: Path | None = None,
    run_logs: list[Path] | None = None,
    human_labels: Path | None = None,
) -> dict[str, Any]:
    """校验全部提交文件。返回 {errors, warnings, coverage, stats}。"""
    errors: list[str] = []
    warnings: list[str] = []
    stats: dict[str, int] = {}

    ds_items: list[tuple[int, dict]] = []
    if dataset is not None:
        ds_items, e = load_jsonl(dataset)
        errors += e
        errors += schema_errors("dataset", ds_items)
        e2, w2 = check_dataset(ds_items)
        errors += e2
        # 公开版没有 expected_abstain / category，跨行一致性检查只对完整版有意义
        if any("ground_truth_answer" in rec for _, rec in ds_items):
            warnings += w2
        stats["dataset_records"] = len(ds_items)
        stats["dataset_kind"] = (
            "full" if any("ground_truth_answer" in rec for _, rec in ds_items) else "public"
        )

    run_items: list[tuple[int, dict]] = []
    for p in run_logs or []:
        items, e = load_jsonl(p)
        errors += e
        errors += schema_errors("run_log", items)
        e2, w2 = check_run_log(items, ds_items if ds_items else None)
        errors += [f"{p.name}  {m}" for m in e2]
        warnings += [f"{p.name}  {m}" for m in w2]
        run_items += items
        stats[f"run_log:{p.name}"] = len(items)

    hl_items: list[tuple[int, dict]] = []
    if human_labels is not None:
        hl_items, e = load_jsonl(human_labels)
        errors += e
        errors += schema_errors("human_labels", hl_items)
        e2, w2 = check_human_labels(
            hl_items,
            ds_items if ds_items else None,
            run_items if run_items else None,
        )
        errors += [f"{human_labels.name}  {m}" for m in e2]
        warnings += [f"{human_labels.name}  {m}" for m in w2]
        stats["human_labels"] = len(hl_items)

    return {
        "errors": errors,
        "warnings": warnings,
        "coverage": coverage_report(run_items),
        "stats": stats,
    }
