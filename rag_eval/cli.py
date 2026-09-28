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
        if name == "dataset_kind":
            print(f"[读取] dataset 版本: {n}（public=发给参赛方的公开版, full=含标准答案的完整版）")
        else:
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

    # 优先级：LLM Judge > 人工标注 > 规则版 approx_correct
    correctness: dict[tuple[str, str], bool] = {}
    if args.human_labels:
        hl_items, e = load_jsonl(Path(args.human_labels))
        for m in e:
            print(f"[错误] {m}")
        for _, rec in hl_items:
            if rec.get("correct") is not None:
                correctness[(rec["question_id"], rec["system_name"])] = bool(rec["correct"])
    if getattr(args, "judge_scores", None):
        import json as _json

        doc = _json.loads(Path(args.judge_scores).read_text(encoding="utf-8"))
        n_judged = 0
        for row in doc.get("per_question", []):
            b = (row.get("binary") or {}).get("correctness")
            if b is not None:
                correctness[(row["question_id"], row["system_name"])] = bool(b)
                n_judged += 1
        print(f"[judge] 用 LLM Judge 覆盖 {n_judged} 条 correctness 判定")

    out = {
        "systems": results_for_all(records, gt_by_id, correctness or None),
        "judge": (
            "llm-judge (binary.correctness)"
            if getattr(args, "judge_scores", None)
            else "rule-based (approx_correct) + human_labels override"
        ),
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


def _load_gt(dataset: str) -> dict[str, dict]:
    items, errs = load_jsonl(Path(dataset))
    for m in errs:
        print(f"[错误] {m}")
    return {rec["question_id"]: rec for _, rec in items}


def _load_runs(paths: list[str]) -> list[dict]:
    out = []
    for p in paths or []:
        items, errs = load_jsonl(Path(p))
        for m in errs:
            print(f"[错误] {p}: {m}")
        out += [rec for _, rec in items]
    return out


def cmd_judge(args: argparse.Namespace) -> int:
    """LLM-as-a-Judge 打分。需要 RAG_JUDGE_BASE_URL / RAG_JUDGE_API_KEY / RAG_JUDGE_MODEL。"""
    import json

    from .judge import JudgeClient, to_binary, to_unit
    from .judge_metrics import judge_records_parallel, summarize

    gt_by_id = _load_gt(args.dataset)
    records = _load_runs(args.run_log)
    client = JudgeClient(
        base_url=args.base_url, api_key=args.api_key, model=args.model, samples=args.samples
    )
    print(f"Judge: {client.model} @ {client.base_url}   样本数/题: {client.samples}")

    rows = []
    # 逐题并发（默认 8 路）；完成顺序不定，结果按输入顺序落盘
    work: list[tuple[dict, dict]] = []
    for rec in records:
        gt = gt_by_id.get(rec.get("question_id"))
        if gt is None:
            continue
        work.append((rec, gt))
    n_done = 0

    def _on_done(_idx: int, scores: dict) -> None:
        nonlocal n_done
        n_done += 1
        done = {m: s["score"] for m, s in scores.items() if s and s.get("score") is not None}
        rec = work[_idx][0]
        print(f"[{n_done}/{len(work)}] {rec.get('question_id')}/{rec.get('system_name')}  {done}")

    all_scores = judge_records_parallel(
        client, work, samples=args.samples, workers=args.workers, on_done=_on_done
    )
    for (rec, _gt), scores in zip(work, all_scores):
        rows.append(
            {
                "question_id": rec.get("question_id"),
                "system_name": rec.get("system_name"),
                "scores": scores,
                "unit": {
                    m: (to_unit(s["score"]) if s and s.get("score") is not None else None)
                    for m, s in scores.items()
                },
                "binary": {
                    m: (to_binary(s["score"]) if s and s.get("score") is not None else None)
                    for m, s in scores.items()
                },
            }
        )

    out = {
        "judge": {"model": client.model, "base_url": client.base_url, "samples": client.samples},
        "per_question": rows,
        "summary": {},
        "api_calls": client.calls,
    }
    by_sys: dict[str, list[dict]] = {}
    for r in rows:
        by_sys.setdefault(r["system_name"], []).append(r)
    for name, rs in by_sys.items():
        out["summary"][name] = summarize(rs)

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    for name, s in out["summary"].items():
        print(f"\n=== {name}")
        for metric, m in s.items():
            if m["mean_score"] is None:
                print(f"  {metric:<18} N/A")
            else:
                print(
                    f"  {metric:<18} {m['mean_score']:.2f}/5  (归一化 {m['mean_unit']:.3f})  "
                    f"n={m['n_scored']}  不稳={m['n_unstable']}"
                )
    print(f"\n共调用 API {client.calls} 次   已写出 {args.out}")
    return 0


def cmd_calibrate(args: argparse.Namespace) -> int:
    """Judge 校准：与人工标注算 Cohen's κ，κ<0.6 不放量（§50）。"""
    import json

    from .calibration import calibrate, to_judge_binary

    judge_doc = json.loads(Path(args.judge_scores).read_text(encoding="utf-8"))
    hl_items, errs = load_jsonl(Path(args.human_labels))
    for m in errs:
        print(f"[错误] {m}")
    human = [rec for _, rec in hl_items]

    report = calibrate(to_judge_binary(judge_doc["per_question"]), human)

    print(f"配对样本 {report['n_paired_total']} 条   κ 均值 {report['kappa_mean']}   闸门 {report['gate']}")
    for metric, m in report["per_metric"].items():
        if m["n_paired"] == 0:
            print(f"  {metric:<14} 无配对样本（跳过）")
            continue
        print(
            f"  {metric:<14} n={m['n_paired']}  一致率={m['agreement_rate']:.2f}  "
            f"κ={m['cohens_kappa']:.3f}  {'PASS' if m['pass'] else 'FAIL'}  {m['confusion']}"
        )
    print(f"\n结论: {report['verdict']}")

    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"已写出 {args.out}")
    return 0 if report["pass"] else 1


def cmd_make_public(args: argparse.Namespace) -> int:
    """发卷：剥离标准答案与一切泄题字段，产出公开版考卷。"""
    from .pack import write_public

    return write_public(
        Path(args.dataset),
        Path(args.out),
        hold_out=args.hold_out,
        hold_out_out=Path(args.hold_out_out) if args.hold_out_out else None,
    )


def cmd_pack(args: argparse.Namespace) -> int:
    """打包参赛方工具箱：公开考卷 + 官方 chunk 库 + 模板 + 校验器。"""
    from .pack import build_kit

    return build_kit(Path(args.dataset), Path(args.out), hold_out=args.hold_out)


def cmd_report(args: argparse.Namespace) -> int:
    """出分报告：results.json -> 单文件 HTML（雷达/热力/归因/Pareto/逐题）。"""
    from .report import write_report

    return write_report(
        Path(args.results),
        Path(args.out),
        title=args.title,
        judge_scores_path=Path(args.judge_scores) if args.judge_scores else None,
    )


def cmd_reveal_categories(args: argparse.Namespace) -> int:
    """收官后公开题型标签，供参赛方按题型复盘。"""
    from .pack import reveal_categories

    return reveal_categories(
        Path(args.dataset), Path(args.out), include_notes=args.notes
    )


def cmd_audit(args: argparse.Namespace) -> int:
    """一致性审计：不看答案对错，只看答题卡的数据自不自洽（反作弊抓手）。"""
    import json

    from .audit import audit_records

    records = _load_runs(args.run_log)
    report = audit_records(records)

    for name, r in report.items():
        mark = {"clean": "干净", "low": "轻微", "medium": "可疑", "high": "高危"}[r["risk"]]
        print(f"\n=== {name}  风险={mark}  命中 {r['flagged_records']}/{r['n_records']} 条")
        if not r["signals"]:
            print("  无异常信号")
        for sig, n in sorted(r["signals"].items(), key=lambda x: -x[1]):
            print(f"  {sig:<26} x{n}")
        shown = 0
        for d in r["details"]:
            for s in d["signals"]:
                if s["level"] == "low" and not args.verbose:
                    continue
                if shown >= args.limit:
                    break
                print(f"    [{s['level']:<6}] {d['question_id']}  {s['signal']}: {s['detail'][:78]}")
                shown += 1

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n已写出 {out}")
    print("提示：命中的是可疑信号不是作弊定罪，每条都可能有正常解释，请人工复核。")
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
    r.add_argument("--judge-scores", help="可选：judge_scores.json，优先级高于人工标注")
    r.add_argument("--out", default="results/results.json")
    r.set_defaults(func=cmd_run)

    j = sub.add_parser("judge", help="LLM-as-a-Judge 打分（Faithfulness/Correctness/Context 等）")
    j.add_argument("--dataset", required=True)
    j.add_argument("--run-log", action="append", required=True)
    j.add_argument("--base-url", help="OpenAI 兼容端点，默认读 RAG_JUDGE_BASE_URL")
    j.add_argument("--api-key", help="默认读 RAG_JUDGE_API_KEY")
    j.add_argument("--model", help="默认读 RAG_JUDGE_MODEL")
    j.add_argument("--samples", type=int, default=3, help="每条判几次取中位（默认 3）")
    j.add_argument("--workers", type=int, default=8,
                   help="逐题并发数（默认 8；限速严格的端点调小，如 4）")
    j.add_argument("--out", default="results/judge_scores.json")
    j.set_defaults(func=cmd_judge)

    c = sub.add_parser("calibrate", help="Judge 校准：与人工标注算 Cohen's κ，κ<0.6 不放量")
    c.add_argument("--judge-scores", required=True)
    c.add_argument("--human-labels", required=True)
    c.add_argument("--out", default="results/calibration.json")
    c.set_defaults(func=cmd_calibrate)

    mp = sub.add_parser("make-public", help="发卷：剥离标准答案与泄题字段，产出公开版考卷")
    mp.add_argument("--dataset", required=True)
    mp.add_argument("--out", default="dataset/dataset_public.jsonl")
    mp.add_argument("--hold-out", type=int, default=0,
                    help="扣留 N 题作暗题（按题型分层抽取），收官补测用")
    mp.add_argument("--hold-out-out", default="dataset/dataset_holdout.jsonl")
    mp.set_defaults(func=cmd_make_public)

    pk = sub.add_parser("pack", help="打包参赛方工具箱 zip（公开考卷+chunk 库+模板+校验器）")
    pk.add_argument("--dataset", required=True)
    pk.add_argument("--out", default="dist/rag-bench-kit.zip")
    pk.add_argument("--hold-out", type=int, default=0,
                    help="扣留 N 题作暗题，不进工具箱，另存为 dist/dataset_holdout.jsonl")
    pk.set_defaults(func=cmd_pack)

    rc = sub.add_parser(
        "reveal-categories",
        help="收官后公开题型标签（category/difficulty/expected_abstain），供参赛方复盘",
    )
    rc.add_argument("--dataset", required=True)
    rc.add_argument("--out", default="dataset/dataset_revealed.jsonl")
    rc.add_argument("--notes", action="store_true", help="连出题备注一起公开")
    rc.set_defaults(func=cmd_reveal_categories)

    rp = sub.add_parser("report", help="出分报告：results.json 转单文件 HTML（双击即开）")
    rp.add_argument("--results", default="results/results.json")
    rp.add_argument("--out", default="results/report.html")
    rp.add_argument("--title", default="RAG 评测对比报告")
    rp.add_argument("--judge-scores", help="可选：judge_scores.json，加画 Judge 一致性一节")
    rp.set_defaults(func=cmd_report)

    ad = sub.add_parser("audit", help="一致性审计：检测硬编码/伪造中间过程的可疑信号")
    ad.add_argument("--run-log", action="append", required=True)
    ad.add_argument("--out", default="results/audit.json")
    ad.add_argument("--limit", type=int, default=12, help="最多打印几条明细（默认 12）")
    ad.add_argument("--verbose", action="store_true", help="连 low 级信号一起打印")
    ad.set_defaults(func=cmd_audit)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
