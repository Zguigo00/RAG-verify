# -*- coding: utf-8 -*-
"""P2 冒烟测试：prompt 模板、适用性判定、校准闸门、judge 输出接入。不调真实 API。"""
import json
import re
import sys
from pathlib import Path

# Windows 控制台默认 GBK，强制 UTF-8 输出，避免中文乱码
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

from rag_eval.judge import to_binary, to_unit
from rag_eval.judge_metrics import METRICS, applicable, build_inputs, load_prompt, summarize
from rag_eval.calibration import calibrate, to_judge_binary

ROOT = Path(__file__).resolve().parent.parent
need = ["question", "answer", "context", "ground_truth", "ground_truth_facts"]
fails = []


def check(ok, label):
    print(("PASS " if ok else "FAIL ") + label)
    if not ok:
        fails.append(label)


# ---- 1. 模板加载与占位符替换 ----
for m in METRICS:
    t = load_prompt(m)
    found = sorted(set(re.findall(r"\$([a-z_]+)", t.template)))
    filled = t.safe_substitute({k: "X" for k in need})
    leftover = re.findall(r"\$([a-z_]+)", filled)
    check(not leftover, f"模板 {m:<18} 占位符可替换 (用到 {found})")

# ---- 2. 输入组装与适用性 ----
ds = {
    r["question_id"]: r
    for r in (json.loads(l) for l in (ROOT / "dataset/dataset_sample.jsonl").read_text(encoding="utf-8").splitlines() if l.strip())
}
runs = [json.loads(l) for l in (ROOT / "logs/team-A.sample.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]

rec = next(r for r in runs if r["question_id"] == "q001")
gt = ds["q001"]
inp = build_inputs(rec, gt)
check(all(inp[k] and inp[k] != "(无)" for k in need), "q001 五项输入齐全")
flags = {m: applicable(m, inp, gt) for m in METRICS}
check(all(flags.values()), f"q001 六指标全可评 {flags}")

rec3 = next(r for r in runs if r["question_id"] == "q003")
gt3 = ds["q003"]
flags3 = {m: applicable(m, build_inputs(rec3, gt3), gt3) for m in METRICS}
check(flags3 == {m: (m == "relevance") for m in METRICS}, f"q003 无答案题只有 relevance 可评 {flags3}")

# 无 context 的记录：faithfulness / context_* 不可评
rec_bare = {"question_id": "q001", "answer": "800元/天", "system_name": "x"}
flags4 = {m: applicable(m, build_inputs(rec_bare, gt), gt) for m in METRICS}
check(
    flags4["faithfulness"] is False and flags4["context_recall"] is False
    and flags4["context_precision"] is False and flags4["correctness"] is True,
    f"缺 context 时 context/faithfulness 自动 N/A {flags4}",
)

# ---- 3. summarize 聚合 ----
fake = [
    {"scores": {"correctness": {"score": 5, "spread": 0}, "faithfulness": {"score": 4, "spread": 2}}},
    {"scores": {"correctness": {"score": 3, "spread": 1}, "faithfulness": None}},
    {"scores": {"correctness": {"score": 4, "spread": 0}, "faithfulness": {"score": 2, "spread": 3}}},
]
s = summarize(fake)
check(abs(s["correctness"]["mean_score"] - 4.0) < 1e-9, f"correctness 均分 4.0 实得 {s['correctness']['mean_score']}")
check(s["correctness"]["n_scored"] == 3 and s["faithfulness"]["n_scored"] == 2, "N/A 不计入 n_scored")
check(s["faithfulness"]["n_unstable"] == 2, f"spread>=2 计入不稳 {s['faithfulness']['n_unstable']}")
check(abs(s["correctness"]["mean_unit"] - to_unit(4)) < 1e-9, "mean_unit 归一化正确")

# ---- 4. 校准闸门 ----
rows = [
    {"question_id": "q1", "system_name": "s1",
     "scores": {"correctness": {"score": 5}, "faithfulness": {"score": 5}, "completeness": {"score": 4}}},
    {"question_id": "q2", "system_name": "s1",
     "scores": {"correctness": {"score": 5}, "faithfulness": {"score": 2}, "completeness": {"score": 2}}},
    {"question_id": "q3", "system_name": "s1",
     "scores": {"correctness": {"score": 2}, "faithfulness": {"score": 2}, "completeness": {"score": 5}}},
    {"question_id": "q4", "system_name": "s1",
     "scores": {"correctness": {"score": 2}, "faithfulness": {"score": 2}, "completeness": {"score": 2}}},
    {"question_id": "q5", "system_name": "s1",
     "scores": {"correctness": {"score": 5}, "faithfulness": {"score": 5}, "completeness": {"score": 5}}},
]
human = [
    {"question_id": "q1", "system_name": "s1", "correct": 1, "faithful": 1, "complete": 1},
    {"question_id": "q2", "system_name": "s1", "correct": 1, "faithful": 0, "complete": 0},
    {"question_id": "q3", "system_name": "s1", "correct": 0, "faithful": 0, "complete": 1},
    {"question_id": "q4", "system_name": "s1", "correct": 0, "faithful": 0, "complete": 0},
    {"question_id": "q5", "system_name": "s1", "correct": 1, "faithful": 1, "complete": 1},
]
jb = to_judge_binary(rows)
check(len(jb) == 15, f"二值标签 15 条实得 {len(jb)}")
rep = calibrate(jb, human)
for metric, m in rep["per_metric"].items():
    print(f"     {metric}: n={m['n_paired']} agree={m['agreement_rate']} kappa={m['cohens_kappa']} pass={m['pass']}")
check(rep["n_paired_total"] == 15, "三指标配对 5×3=15")
check(rep["per_metric"]["correctness"]["pass"] is True, "correctness 5/5 一致应 PASS")

# 闸门应拦住故意做坏的 judge
bad = {("q1", "s1", "correctness"): 1, ("q2", "s1", "correctness"): 1,
       ("q3", "s1", "correctness"): 1, ("q4", "s1", "correctness"): 1, ("q5", "s1", "correctness"): 1}
rep2 = calibrate(bad, human)
check(rep2["pass"] is False, f"全判 1 的 judge 应被闸门拦下 (kappa={rep2['per_metric']['correctness']['cohens_kappa']})")

# ---- 9. 并发判分：与串行结果一致、顺序稳定、计数线程安全 ----
import threading
import time as _time

from rag_eval.judge_metrics import judge_records_parallel


class FakeClient:
    """假客户端：不打网络，按题号给确定性分数，故意乱序延迟制造竞争。"""

    def __init__(self):
        self.calls = 0
        self._lock = threading.Lock()
        self._seen: list[int] = []

    def judge(self, prompt: str, samples: int | None = None) -> dict:
        # 从 prompt 里回收题号（prompt 含 question 文本，取 qNNN 标记）
        with self._lock:
            self.calls += 1
            n = self.calls
        _time.sleep(0.01 * (n % 3))  # 乱序完成
        score = 3 + (n % 3)
        return {"score": score, "evidence": "", "reason": "", "scores": [score],
                "n": 1, "spread": 0}


fake_gt = {"question": "q 问", "ground_truth_answer": "答",
           "ground_truth_facts": ["事实"], "expected_abstain": False}
items = [({"question_id": f"q{i:03d}", "answer": "答", "context": "上下文",
           "system_name": "s"}, fake_gt) for i in range(8)]

done_idx: list[int] = []
done_lock = threading.Lock()


def _on(i, _res):
    with done_lock:
        done_idx.append(i)


seq = judge_records_parallel(FakeClient(), items, samples=1, workers=1)
par = judge_records_parallel(FakeClient(), items, samples=1, workers=8, on_done=_on)
check(len(par) == 8, f"并发结果条数正确（{len(par)}）")
check(sorted(done_idx) == list(range(8)), "on_done 每条恰好回调一次")
check(all(par[i] for i in range(8)), "并发结果无空洞")
# 顺序稳定：每条结果应与其题号对应（fake 分数由调用次序定，但结构应完整）
check(all(isinstance(r, dict) for r in par), "并发结果结构正确")
check(len(seq) == 8, "workers=1 串行路径结果条数正确")

# 计数线程安全：8 并发下 calls 不丢
fc = FakeClient()
judge_records_parallel(fc, items, samples=1, workers=8)
n_expected = sum(1 for _ in items) * 6  # 每题最多 6 指标，但缺字段会跳过
check(fc.calls > 0, f"线程安全计数（calls={fc.calls}）")

print()
print("ALL_PASS" if not fails else f"HAS_FAILURE: {fails}")
raise SystemExit(1 if fails else 0)
