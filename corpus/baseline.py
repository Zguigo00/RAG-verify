"""朴素关键词检索 baseline：把 corpus/chunks.jsonl 当语料，出一份 run_log。

作用有二：
1. 验收语料与考卷 —— 真实 50 题能端到端跑通指标链
2. 给参赛方一个「必须超越」的地板分（纯词面匹配，无 embedding 无 rerank）

评分方式：chunk 与 query 的词重合率（Jaccard），取 Top-K。
加一个可选的「噪声注入」概率，模拟把无关 chunk 塞进 context，用于演示 Context Precision 的差异。

    python corpus/baseline.py --dataset dataset/dataset_v1.jsonl --out logs/baseline.jsonl
"""
from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def tokenize(text: str) -> set[str]:
    """中英文混合分词：英文/数字按词，中文按双字滑窗。足够当 baseline。"""
    out = set(re.findall(r"[A-Za-z0-9_]+", text.lower()))
    han = re.findall(r"[一-鿿]", text)
    for i in range(len(han) - 1):
        out.add(han[i] + han[i + 1])
    out.update(han)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", required=True)
    ap.add_argument("--out", default="logs/baseline.jsonl")
    ap.add_argument("--top-k", type=int, default=5)
    ap.add_argument("--limit", type=int, default=0,
                    help="只跑前 N 题（冒烟测试用，0=全跑）")
    ap.add_argument("--noise", type=float, default=0.3,
                    help="注入无关 chunk 的比例，模拟 Top-K 塞垃圾（默认 0.3）")
    args = ap.parse_args()

    chunks = [json.loads(l) for l in (ROOT / "chunks.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    for c in chunks:
        c["_toks"] = tokenize(c["text"] + " " + c["title"] + " " + c["doc_id"])

    rows = [json.loads(l) for l in Path(args.dataset).read_text(encoding="utf-8").splitlines() if l.strip()]
    if args.limit:
        rows = rows[: args.limit]
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    t_all = time.perf_counter()
    with out_path.open("w", encoding="utf-8") as f:
        for i, gt in enumerate(rows, 1):
            t0 = time.perf_counter()
            qtoks = tokenize(gt["question"])
            scored = sorted(
                chunks,
                key=lambda c: len(qtoks & c["_toks"]) / max(len(qtoks | c["_toks"]), 1),
                reverse=True,
            )
            picked = scored[: args.top_k]
            # 注入噪声：把排名最末的无关 chunk 换进来，模拟精度损失
            n_noise = int(len(picked) * args.noise)
            if n_noise and len(scored) > len(picked):
                picked = picked[: len(picked) - n_noise] + scored[-n_noise:]
                picked = sorted(picked, key=lambda c: len(qtoks & c["_toks"]), reverse=True)

            ctx = "\n".join(f"[{j}] {c['text']}" for j, c in enumerate(picked, 1))
            rec = {
                "system_name": "baseline_keyword",
                "question_id": gt["question_id"],
                "answer": "",
                "abstained": False,
                "retrieved_chunks": [
                    {"chunk_id": c["chunk_id"], "doc_id": c["doc_id"], "rank": j,
                     "score": round(len(qtoks & c["_toks"]) / max(len(qtoks | c["_toks"]), 1), 4),
                     "text": c["text"]}
                    for j, c in enumerate(picked, 1)
                ],
                "context": ctx,
                "citations": [],
                "latency_ms": round((time.perf_counter() - t0) * 1000, 1),
                "input_tokens": len(ctx) // 2,
                "output_tokens": 0,
                "error": None,
            }
            # 无答案题：baseline 看不出语义，一律作答（幻觉），用来验 Abstention 指标
            if gt.get("expected_abstain"):
                rec["answer"] = "相关信息如下。"
            else:
                rec["answer"] = picked[0]["text"][:80] if picked else ""
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            print(f"[{i}/{len(rows)}] {gt['question_id']}  用时 {rec['latency_ms']}ms")

    print(f"\n已写出 {out_path}   总用时 {time.perf_counter() - t_all:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
