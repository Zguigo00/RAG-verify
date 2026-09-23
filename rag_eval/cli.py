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

from .validate import validate_files


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

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
