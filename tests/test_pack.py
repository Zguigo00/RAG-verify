# -*- coding: utf-8 -*-
"""发卷与打包的泄题回归测试。

公开版考卷一旦泄题就不可挽回（对方拿走就能读到标准答案），所以这里既有正向校验，
也有故意喂进泄题数据的负向用例，确认拦截真的会响。
"""
import json
import zipfile
from pathlib import Path

from rag_eval.pack import (
    FORBIDDEN_SUBSTRINGS,
    PUBLIC_FIELDS,
    assert_no_leak,
    build_kit,
    make_public_rows,
    write_public,
)
from rag_eval.validate import schema_errors

ROOT = Path(__file__).resolve().parent.parent
fails = []


def check(ok, label):
    print(("PASS " if ok else "FAIL ") + label)
    if not ok:
        fails.append(label)


raw = [
    json.loads(l)
    for l in (ROOT / "dataset/dataset_v1.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()
]
public = make_public_rows(raw)

# ---- 1. 只保留白名单字段 ----
keys = set()
for r in public:
    keys |= set(r)
check(keys == set(PUBLIC_FIELDS), f"公开版字段恰为 {PUBLIC_FIELDS}（实得 {sorted(keys)}）")

# ---- 2. 禁用字段名不得出现 ----
bad_keys = [k for k in keys if any(b in k.lower() for b in FORBIDDEN_SUBSTRINGS)]
check(not bad_keys, f"无禁用字段名（实得 {bad_keys}）")

# ---- 3. 标准答案原文不得出现 ----
text = json.dumps(public, ensure_ascii=False)
leaked = [
    (r["question_id"], r["ground_truth_answer"][:30])
    for r in raw
    if len((r.get("ground_truth_answer") or "").strip()) >= 8
    and r["ground_truth_answer"].strip() in text
]
check(not leaked, f"标准答案原文未出现在公开版（泄漏 {leaked}）")

# ---- 4. 逐题号比对，确认答案确实不在同号记录里 ----
pub_by_id = {r["question_id"]: r for r in public}
mismatch = [
    r["question_id"]
    for r in raw
    if r.get("ground_truth_answer")
    and r["ground_truth_answer"].strip()
    and r["ground_truth_answer"].strip() in json.dumps(pub_by_id.get(r["question_id"], {}), ensure_ascii=False)
]
check(not mismatch, f"逐题比对无答案泄漏（泄漏 {mismatch}）")

# ---- 5. 负向用例：故意泄题必须被拦截 ----
evil = [{"question_id": "x", "question": "q", "domain": "enterprise",
         "expected_abstain": False, "category": "no_answer"}]
try:
    assert_no_leak(evil, [])
    check(False, "含 expected_abstain/category 的记录应被拦截")
except SystemExit as e:
    check("泄题拦截" in str(e), f"负向用例1 被拦截: {str(e)[:50]}")

evil2 = [{"question_id": "x", "question": "问题是：国内一线城市住宿费标准为800元/天。",
          "domain": "enterprise"}]
evil2_raw = [{"question_id": "x", "ground_truth_answer": "国内一线城市住宿费标准为800元/天"}]
try:
    assert_no_leak(evil2, evil2_raw)
    check(False, "答案原文泄漏应被拦截")
except SystemExit as e:
    check("泄题拦截" in str(e), f"负向用例2 被拦截: {str(e)[:50]}")

# ---- 6. schema 校验：公开版走 dataset_public，完整版走 dataset ----
pub_items = list(enumerate(public, 1))
full_items = list(enumerate(raw, 1))
check(not schema_errors("dataset", pub_items), "公开版通过 dataset_public.schema.json")
check(not schema_errors("dataset", full_items), "完整版通过 dataset.schema.json")

# ---- 7. 端到端：打包并检查 zip 内不得含 ground_truth ----
out_zip = ROOT / "dist" / "_test_kit.zip"
build_kit(ROOT / "dataset/dataset_v1.jsonl", out_zip)
names = zipfile.ZipFile(out_zip).namelist()
check("README.md" in names and "dataset/dataset_public.jsonl" in names, f"zip 含 README 与公开考卷（{len(names)} 文件）")
check("corpus/chunks.jsonl" in names and "templates/adapter_template.py" in names, "zip 含 chunk 库与接入模板")
check(not any("ground_truth" in n or "dataset_v1" in n for n in names), "zip 内无 ground_truth / dataset_v1")
inner = zipfile.ZipFile(out_zip).read("dataset/dataset_public.jsonl").decode("utf-8")
inner_leak = [r["question_id"] for r in raw
              if len((r.get("ground_truth_answer") or "").strip()) >= 8
              and r["ground_truth_answer"].strip() in inner]
check(not inner_leak, f"zip 内考卷无答案泄漏（{inner_leak}）")
out_zip.unlink()

print()
print("ALL_PASS" if not fails else f"HAS_FAILURE: {fails}")
raise SystemExit(1 if fails else 0)
