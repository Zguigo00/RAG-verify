# -*- coding: utf-8 -*-
"""report 命令回归测试：单文件 HTML 报告的结构与降级路径。

报告是给人看的最终产物，坏在这里就是白跑一场评测：
- 每个 section 必须闭合、无 None/nan 泄漏到 HTML
- hover 层、表格视图、深色模式三件套必须在
- N/A 必须显式标注，不能画成 0
- >3 系统时 Pareto 散点自动降级 emphasis 编码（all-pairs 调色板约束）
"""
import json
import sys
from pathlib import Path

# Windows 控制台默认 GBK，强制 UTF-8 输出，避免中文乱码
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

from rag_eval.report import render

ROOT = Path(__file__).resolve().parent.parent
fails = []


def check(ok, label):
    print(("PASS " if ok else "FAIL ") + label)
    if not ok:
        fails.append(label)


d = json.loads((ROOT / "results" / "results_sample.json").read_text(encoding="utf-8"))
h = render(d)

# ---- 1. 结构完整性 ----
check("<svg" in h, "含内联 SVG")
check(h.count("<section") == h.count("</section>"), "section 闭合")
check("None" not in h, "无 None 泄漏到 HTML")
check("nan" not in h.lower().replace("financ", ""), "无 NaN 泄漏到 HTML")

# ---- 2. 六个视图齐全 ----
for heading in ["排行榜", "指标雷达", "题型 × 系统", "行业 × 系统", "错误归因", "Pareto 权衡", "逐题对比"]:
    check(heading in h, f"含「{heading}」")

# ---- 3. 可访问性三件套 ----
check(h.count("data-tip") > 10, f"hover 层齐全（{h.count('data-tip')} 个 tip）")
check("表格视图" in h and "<table" in h, "表格视图兜底")
check("切换主题" in h and "data-theme" in h, "深色模式可用")
check("legend" in h, "图例存在（≥2 系列）")

# ---- 4. N/A 语义：显式标注，不画成 0 ----
check("N/A" in h, "N/A 显式标注")
check("不计 0 分" in h, "注明 N/A 不计 0 分")

# ---- 5. >3 系统降级 emphasis（all-pairs 调色板约束）----


def mk(name, corr, lat):
    return {
        "system_name": name, "n_questions": 3, "n_judged": 3, "correct_rate": corr,
        "retrieval": {"hit@5": corr, "recall@5": corr, "mrr@5": corr, "ndcg@5": corr},
        "by_category": {}, "by_domain": {},
        "system": {"latency_p95_ms": lat, "cost_per_query_usd": 0.001, "error_rate": 0.0},
        "error_breakdown": {}, "per_question": [], "pareto": False,
    }


five = {
    "systems": {n: mk(n, c, l) for n, c, l in zip(
        ["a", "b", "c", "d", "e"], [0.9, 0.7, 0.5, 0.3, 0.1], [100, 200, 300, 400, 500])},
    "judge": "x", "pareto_front": ["a"],
}
h5 = render(five)
check("Pareto 前沿" in h5 and "被支配" in h5, ">3 系统走 emphasis 编码")

# ---- 6. 单系统不画图例框（标题已命名系列）----
solo = {"systems": {"only": mk("only", 0.5, 100)}, "judge": "x", "pareto_front": []}
hs = render(solo)
check("指标雷达" in hs, "单系统仍出图")

print()
print("ALL_PASS" if not fails else f"HAS_FAILURE: {fails}")
raise SystemExit(1 if fails else 0)
