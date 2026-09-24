"""rag-eval 命令行入口。

用法:
    python -m rag_eval.cli validate --dataset dataset.jsonl --run-log run_log.jsonl
    python -m rag_eval.cli validate --dataset dataset.jsonl --run-log team-a.jsonl --run-log team-b.jsonl --human-labels human_labels.jsonl

退出码: 0=通过（可能有 warning）, 1=有 error。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .validate import load_jsonl, validate_files


def cmd_validate(args: argparse.Namespace) -> int:
    result = validate_files(
        dataset=Path(args.dataset) if args.dataset else None,
        run_logs=[Path(p) for p in (args.run_log or [])],
        human_labels=Path(args.human_labels) if args.human_labels else None,
    )

    errors, warnings = result["errors"], result["warnings"]

    for name, n in result["stats"].items():
        print(f"[读取] {name}: {n} 条")

    for w in warnings:
        print(f"[警告] {w}")
    for e in errors:
        print(f"[错误] {e}")

    for system, info in result["coverage"].items():
        print(f"\n[覆盖率] {system}  共 {info['n_questions']} 题")
        for layer, s in info["layers"].items():
            flag = "可评" if s["computable"] else "N/A "
            print(
                f"    {flag}  {layer:<6} {s['covered']}/{s['total']} 条有数据"
                f"（{s['pct']}%）  {s['label']}"
            )
        missing = [s["label"] for s in info["layers"].values() if not s["computable"]]
        if missing:
            print(f"    → 缺字段，以下指标将显示 N/A（不计 0 分）: {'; '.join(missing)}")

    print(f"\n[结果] {len(errors)} 个错误, {len(warnings)} 个警告")
    return 1 if errors else 0


def cmd_run(args: argparse.Namespace) -> int:
    """确定性评测：检索指标 + 系统指标 + 错误归因 + 题型分组 + Pareto。不调 LLM。"""
    import json

    from .aggregate import pareto_front, results_for_all

    ds_items, e = load_jsonl(Path(args.dataset))
    for m in e:
        print(f"[错误] {m}")
    gt_by_id = {rec["question_id"]: rec for _, rec in ds_items}

    run_items: list[tuple[int, dict]] = []
    for p in args.run_log or []:
        items, e = load_jsonl(Path(p))
        for m in e:
            print(f"[错误] {p}: {m}")
        run_items += items
    records = [rec for _, rec in run_items]

    # 人工标注覆盖规则版正确性判定（P2 会再叠加 LLM Judge）
    correctness: dict[tuple[str, str], bool] = {}
    if args.human_labels:
        hl_items, e = load_jsonl(Path(args.human_labels))
        for m in e:
            print(f"[错误] {m}")
        for _, rec in hl_items:
            if rec.get("correct") is not None:
                correctness[(rec["question_id"], rec["system_name"])] = bool(rec["correct"])

    out = {
        "systems": results_for_all(records, gt_by_id, correctness or None),
        "judge": "rule-based (approx_correct) + human_labels override",
    }
    front = pareto_front(out["systems"])
    out["pareto_front"] = front

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(f"系统数: {len(out['systems'])}   Pareto 前沿: {front or '(空)'}")
    for name, r in out["systems"].items():
        ret = r["retrieval"]
        sysm = r["system"]
        print(f"\n=== {name}  pareto={r['pareto']}")
        print(f"  correct_rate {r['correct_rate']}   "
              f"hit@5 {ret.get('hit@5')}  mrr@5 {ret.get('mrr@5')}  "
              f"ndcg@5 {ret.get('ndcg@5')}  p@5 {ret.get('precision@5')}")
        print(f"  latency_p95 {sysm['latency_p95_ms']}ms  cost/q {sysm['cost_per_query_usd']}  "
              f"error_rate {sysm['error_rate']}")
        if r["error_breakdown"]:
            print(f"  error_breakdown {r['error_breakdown']}")
        for cat, c in r["by_category"].items():
            cr = c["correct_rate"]
            cr = f"{cr:.2f}" if cr is not None else "N/A"
            print(f"    [{cat:<9}] n={c['n']}  correct_rate={cr}")
    print(f"\n已写出 {args.out}")
    return 0


def main(argv: list[str] | None = None) -> int:
    # Windows 控制台默认 GBK，强制 UTF-8 输出，避免中文乱码
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(prog="rag-eval", description="RAG 质量评测工具")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("validate", help="校验提交文件（schema + 一致性 + 覆盖率）")
    p.add_argument("--dataset", help="dataset.jsonl 路径")
    p.add_argument(
        "--run-log",
        action="append",
        help="run_log.jsonl 路径，可多次指定（每个系统一份）",
    )
    p.add_argument("--human-labels", help="human_labels.jsonl 路径")
    p.set_defaults(func=cmd_validate)

    r = sub.add_parser("run", help="确定性评测：检索/系统指标 + 错误归因 + Pareto（不调 LLM）")
    r.add_argument("--dataset", required=True)
    r.add_argument("--run-log", action="append", required=True)
    r.add_argument("--human-labels", help="可选：人工标注，覆盖规则版正确性判定")
    r.add_argument("--out", default="results/results.json")
    r.set_defaults(func=cmd_run)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
