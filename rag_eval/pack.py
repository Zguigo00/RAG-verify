"""发卷与打包：把考卷 + 语料 + 模板打成参赛方工具箱。

为什么要单独一条 make-public：dataset_v1.jsonl 含标准答案，直接发等于发答案。
剥离清单里容易漏的是后四项 —— 它们同样泄题：

  expected_abstain  无答案题标记 -> 告诉对方「这题该拒答」，Abstention 指标直接失效
  category          no_answer / temporal / multi_hop -> 提示检索策略
  difficulty        hard -> 提示这题有坑
  notes             出题备注，含设计意图

所以公开版只保留 question_id / question / domain 三样。
"""
from __future__ import annotations

import json
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# 公开版保留的字段白名单。加字段前先问：这会不会泄露作答线索？
PUBLIC_FIELDS = ("question_id", "question", "domain")

# 泄题字段黑名单 —— 即便未来有人往 dataset 里加了新字段，这里也兜一层
FORBIDDEN_SUBSTRINGS = (
    "ground_truth", "expected_abstain", "category", "difficulty", "notes", "answer",
)

# 工具箱里要带的文件（相对仓库根目录）。保留原目录结构，
# 这样参赛方解压后 `python -m rag_eval.cli validate` 能直接跑通。
KIT_FILES = [
    "requirements.txt",
    "schemas/dataset.schema.json",
    "schemas/dataset_public.schema.json",
    "schemas/run_log.schema.json",
    "schemas/human_labels.schema.json",
    "rag_eval/__init__.py",
    "rag_eval/cli.py",
    "rag_eval/validate.py",
    "corpus/domains.json",
    "corpus/chunks.jsonl",
    "corpus/chunk_index.json",
    "templates/adapter_template.py",
    "templates/接入说明.md",
]
KIT_GLOBS = ["corpus/enterprise/*.md", "corpus/ecommerce/*.md"]


def make_public_rows(rows: list[dict]) -> list[dict]:
    """剥离标准答案，只留作答必需字段。"""
    out = []
    for r in rows:
        out.append({k: r[k] for k in PUBLIC_FIELDS if k in r})
    return out


def assert_no_leak(public_rows: list[dict], raw_rows: list[dict]) -> None:
    """发卷前的兜底自检：公开版不得残留任何泄题字段或答案文本。"""
    text = json.dumps(public_rows, ensure_ascii=False)
    for r in public_rows:
        for key in r:
            low = key.lower()
            for bad in FORBIDDEN_SUBSTRINGS:
                if bad == "answer" and low == "question_id":
                    continue  # question_id 里含 "id" 无害，但下面统一查 answer 子串
                if bad in low:
                    raise SystemExit(f"[泄题拦截] 公开版含禁用字段 `{key}`")

    # 答案文本本身也不得出现在公开版里
    leaked = []
    for r in raw_rows:
        for field in ("ground_truth_answer",):
            v = (r.get(field) or "").strip()
            if len(v) >= 8 and v in text:
                leaked.append((r.get("question_id"), v[:40]))
    if leaked:
        raise SystemExit(f"[泄题拦截] 答案原文出现在公开版: {leaked}")


def write_public(dataset: Path, out: Path) -> int:
    rows = [json.loads(l) for l in dataset.read_text(encoding="utf-8").splitlines() if l.strip()]
    public = make_public_rows(rows)
    assert_no_leak(public, rows)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in public) + "\n", encoding="utf-8"
    )
    print(f"[发卷] {len(public)} 题 -> {out}")
    print(f"[发卷] 保留字段: {', '.join(PUBLIC_FIELDS)}（ground_truth_* / category / difficulty / expected_abstain / notes 已剥离）")
    return 0


# 工具箱 README 单独成文件（templates/kit_README.md），就地可读可版本化
README = (ROOT / "templates" / "kit_README.md").read_text(encoding="utf-8")


def build_kit(dataset: Path, out_zip: Path) -> int:
    rows = [json.loads(l) for l in dataset.read_text(encoding="utf-8").splitlines() if l.strip()]
    public = make_public_rows(rows)
    assert_no_leak(public, rows)

    out_zip.parent.mkdir(parents=True, exist_ok=True)
    missing = []
    with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("README.md", README)
        z.writestr(
            "dataset/dataset_public.jsonl",
            "\n".join(json.dumps(r, ensure_ascii=False) for r in public) + "\n",
        )
        for rel in KIT_FILES:
            p = ROOT / rel
            if p.exists():
                z.write(p, rel)
            else:
                missing.append(rel)
        for pattern in KIT_GLOBS:
            for p in sorted(ROOT.glob(pattern)):
                z.write(p, str(p.relative_to(ROOT)).replace("\\", "/"))

    n = len(zipfile.ZipFile(out_zip).namelist())
    print(f"[打包] {n} 个文件 -> {out_zip}  ({out_zip.stat().st_size // 1024} KB)")
    print(f"[打包] 公开考卷 {len(public)} 题（已剥离标准答案）")
    if missing:
        print(f"[警告] 以下文件缺失未打入: {missing}")
    return 0
