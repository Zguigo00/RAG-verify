# -*- coding: utf-8 -*-
"""一致性审计与暗题抽样的回归测试。

这两项是接住「刷分漏洞」反馈后的回应：
- audit 必须区分真跑与伪造（伪造判高危，真数据零误报）
- hold-out 必须每种题型都有暗题（否则按题型硬编码照样过）
"""
import json
from collections import Counter
from pathlib import Path

from rag_eval.audit import audit_record, audit_records
from rag_eval.pack import pick_holdout

ROOT = Path(__file__).resolve().parent.parent
fails = []


def check(ok, label):
    print(("PASS " if ok else "FAIL ") + label)
    if not ok:
        fails.append(label)


real = [
    json.loads(l)
    for l in (ROOT / "logs/baseline_keyword.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()
]
rows = [
    json.loads(l)
    for l in (ROOT / "dataset/dataset_v1.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()
]

# ---- 1. 真实跑出来的数据必须零误报 ----
rep = audit_records(real)
r = next(iter(rep.values()))
check(r["risk"] == "clean" and r["flagged_records"] == 0,
      f"真实 baseline 零误报（risk={r['risk']}, 命中 {r['flagged_records']}/{r['n_records']}）")

# ---- 2. 伪造答卷必须判高危 ----
forged = [{
    "system_name": "cheater", "question_id": f"q{i}", "answer": "标准答案",
    "context": "直接抄标准答案块" * 30, "input_tokens": 12, "latency_ms": 1200.0,
    "retrieved_chunks": [{"chunk_id": f"x{i}", "rank": j, "score": 0.9, "text": "原文"} for j in range(1, 4)],
    "citations": [{"claim": "对不上的引用", "chunk_id": "x1"}],
    "trace": {"emb": 200, "search": 200, "llm": 200},
} for i in range(20)]
rep2 = audit_records(forged)
r2 = next(iter(rep2.values()))
check(r2["risk"] == "high", f"伪造答卷判高危（risk={r2['risk']}）")
for want in ("score_constant", "token_context_mismatch", "claim_not_in_answer", "latency_degenerate"):
    check(want in r2["signals"], f"命中信号 {want}")

# ---- 3. 逐个物理约束的单测 ----
sig = lambda rec, name: any(s["signal"] == name for s in audit_record(rec))
check(sig({"answer": "a", "context": "长" * 300, "input_tokens": 5, "system_name": "t"},
          "token_context_mismatch"), "context 长而 token 少 -> token_context_mismatch")
check(sig({"answer": "a", "context": "短", "input_tokens": 5000, "latency_ms": 3, "system_name": "t"},
          "latency_impossible"), "耗时不可能 -> latency_impossible")
check(sig({"answer": "a", "latency_ms": 1000, "trace": {"a": 400, "b": 400, "c": 400}, "system_name": "t"},
          "trace_over_total"), "trace 之和超过总耗时 -> trace_over_total")
check(not audit_record({
    "answer": "国内 100 元/天", "system_name": "t", "input_tokens": 1500, "latency_ms": 1187,
    "context": "## 伙食补助\n国内 100 元/天。\n" * 60,
    "retrieved_chunks": [{"chunk_id": "a", "rank": 1, "score": 0.74},
                         {"chunk_id": "b", "rank": 2, "score": 0.69}],
    "citations": [{"claim": "国内 100 元/天", "chunk_id": "a"}],
    "trace": {"emb": 41, "llm": 812}}), "自洽记录无信号")

# ---- 4. 暗题必须覆盖全部题型 ----
all_cats = {r["category"] for r in rows}
for n in (8, 10, 20, 40):
    held, pub = pick_holdout(rows, n)
    missing = all_cats - {h["category"] for h in held}
    check(len(held) == n and len(held) + len(pub) == len(rows) and not missing,
          f"--hold-out {n}: 数量对且每类都有暗题（缺 {missing or '无'}）")

# ---- 5. 边界 ----
held, pub = pick_holdout(rows, 0)
check(len(held) == 0 and len(pub) == len(rows), "--hold-out 0 不扣留")
held, pub = pick_holdout(rows, 999)
check(len(held) == len(rows) and len(pub) == 0, "--hold-out 超量时封顶为全量")
held, _ = pick_holdout(rows, 3)
check(len(held) == 3, f"--hold-out 3（小于题型数）仍取到 3 题: {Counter(h['category'] for h in held)}")

print()
print("ALL_PASS" if not fails else f"HAS_FAILURE: {fails}")
raise SystemExit(1 if fails else 0)
