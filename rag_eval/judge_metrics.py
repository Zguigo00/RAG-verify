"""指标组装：加载 prompts/ 模板 → 填字段 → 调 Judge → 汇总打分。

每个指标一个 prompt 文件（prompts/<metric>.md，string.Template 的 $var 占位），
改 rubric 只改 md，不动代码。

字段缺失就不评该指标（返回 None），与 run_log 契约的「缺字段显示 N/A」一致。
"""
from __future__ import annotations

from pathlib import Path
from string import Template

from .judge import JudgeClient, to_unit

PROMPT_DIR = Path(__file__).resolve().parent.parent / "prompts"

# metric -> (模板文件, 需要的输入键)
# 参与人工校准的指标在 calibration.py 里对齐到 human_labels 的字段
METRICS: dict[str, tuple[str, tuple[str, ...]]] = {
    "faithfulness": ("faithfulness.md", ("context", "answer")),
    "correctness": ("correctness.md", ("question", "ground_truth", "answer")),
    "relevance": ("relevance.md", ("question", "answer")),
    "completeness": ("completeness.md", ("question", "ground_truth_facts", "answer")),
    "context_recall": ("context_recall.md", ("ground_truth_facts", "context")),
    "context_precision": ("context_precision.md", ("question", "ground_truth_facts", "context")),
}

# 无答案题只评 relevance（拒答是否答到点上），其余指标无定义
ABSTAIN_METRICS = ("relevance",)


def load_prompt(metric: str) -> Template:
    fname = METRICS[metric][0]
    return Template((PROMPT_DIR / fname).read_text(encoding="utf-8"))


def build_inputs(rec: dict, gt: dict) -> dict[str, str]:
    """run_log + ground truth -> prompt 占位符的值。"""
    facts = gt.get("ground_truth_facts") or []
    return {
        "question": rec.get("__question__") or gt.get("question", ""),
        "answer": rec.get("answer") or "",
        "context": rec.get("context") or "",
        "ground_truth": gt.get("ground_truth_answer") or "",
        "ground_truth_facts": "\n".join(f"- {f}" for f in facts) or "(无)",
    }


def applicable(metric: str, inputs: dict[str, str], gt: dict) -> bool:
    """输入不齐就不评该指标（算 N/A，不计 0 分）。"""
    if gt.get("expected_abstain") and metric not in ABSTAIN_METRICS:
        return False
    keys = METRICS[metric][1]
    for k in keys:
        v = inputs.get(k, "")
        if not v or v == "(无)":
            return False
    return True


def judge_record(
    client: JudgeClient,
    rec: dict,
    gt: dict,
    metrics: tuple[str, ...] | None = None,
    samples: int | None = None,
) -> dict:
    """单条记录跑全部指标。返回 {metric: result | None}。"""
    inputs = build_inputs(rec, gt)
    out: dict[str, dict | None] = {}
    for metric in metrics or tuple(METRICS):
        if not applicable(metric, inputs, gt):
            out[metric] = None
            continue
        prompt = load_prompt(metric).safe_substitute(inputs)
        try:
            out[metric] = client.judge(prompt, samples=samples)
        except Exception as e:  # 单指标失败不拖垮整条
            out[metric] = {"score": None, "error": str(e), "evidence": "", "reason": "",
                           "scores": [], "n": 0, "spread": 0}
    return out


def judge_records_parallel(
    client: JudgeClient,
    items: list[tuple[dict, dict]],
    samples: int | None = None,
    workers: int = 8,
    on_done=None,
) -> list[dict]:
    """并发跑多条记录的判分，结果按输入顺序返回。

    串行下全量 50 题约 750 次调用 × 5s ≈ 1 小时；8 路并发压到 ~8 分钟。
    - 逐题并发、题内串行：一题的 6 个指标共享同一份上下文拼接，串行更稳，
      而题间毫无依赖，是天然的并行粒度
    - 单条失败不拖垮整批（judge_record 内部已兜住单指标异常）
    - on_done(idx, result) 每完成一条回调一次，供 CLI 打进度（回调在工作线程里，
      由调用方自己保证线程安全）
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    if not items:
        return []
    results: list[dict | None] = [None] * len(items)
    n_workers = max(1, min(workers, len(items)))

    def _one(i: int) -> tuple[int, dict]:
        rec, gt = items[i]
        return i, judge_record(client, rec, gt, samples=samples)

    if n_workers == 1:  # 顺序执行，便于调试与单线程环境
        for i in range(len(items)):
            idx, res = _one(i)
            results[idx] = res
            if on_done:
                on_done(idx, res)
        return [r or {} for r in results]

    with ThreadPoolExecutor(max_workers=n_workers) as ex:
        futures = [ex.submit(_one, i) for i in range(len(items))]
        for fut in as_completed(futures):
            idx, res = fut.result()
            results[idx] = res
            if on_done:
                on_done(idx, res)
    return [r or {} for r in results]


def summarize(records_scores: list[dict]) -> dict[str, dict]:
    """跨记录聚合各指标：均分（1-5 与归一化 0-1）、有效条数、不稳条数。"""
    out: dict[str, dict] = {}
    for metric in METRICS:
        vals, unit, spreads, errs = [], [], [], 0
        for r in records_scores:
            # 兼容 judge_record 的扁平结构与 cmd_judge 的 {scores: {...}} 包装
            res = (r.get("scores") or r).get(metric)
            if not res or res.get("score") is None:
                if res and res.get("error"):
                    errs += 1
                continue
            vals.append(res["score"])
            unit.append(to_unit(res["score"]))
            if res.get("spread", 0) >= 2:
                spreads.append(res["spread"])
        n = len(vals)
        out[metric] = {
            "mean_score": sum(vals) / n if n else None,
            "mean_unit": sum(unit) / n if n else None,  # 0-1，进雷达图
            "n_scored": n,
            "n_error": errs,
            "n_unstable": len(spreads),  # spread>=2，建议人工复核
        }
    return out
