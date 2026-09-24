"""语料切分：corpus/<domain>/*.md -> chunks.jsonl + chunk_index.json

切分规则（刻意保持简单稳定，保证 chunk_id 可复现）：
  每份文档一个 .md，每个 `## ` 小节 = 1 个 chunk
  chunk_id = <doc_id>__<NNN>   NNN = 小节序号（1 起，三位补零）

标题行（`# `）与小节前的正文算 chunk_000（文档级元信息：版本号/生效日期），
这样「2025版/2024版」的版本标注本身也是一个可检索的 chunk，版本混淆题才有对比物。

产出：
  corpus/chunks.jsonl      [{chunk_id, doc_id, domain, section_index, title, text}, ...]
  corpus/chunk_index.json  对照表：chunk_id -> {doc_id, domain, title, line_start, line_end}
                           参赛方用它把 ground_truth 的 chunk_id 映射回文档位置
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CORPUS = ROOT
OUT_CHUNKS = CORPUS / "chunks.jsonl"
OUT_INDEX = CORPUS / "chunk_index.json"


def split_doc(path: Path, domain: str) -> list[dict]:
    lines = path.read_text(encoding="utf-8").splitlines()
    doc_id = path.stem
    chunks: list[dict] = []
    cur_title = "(文档头)"
    cur_start = 1
    buf: list[str] = []

    def flush(end_line: int) -> None:
        text = "\n".join(buf).strip()
        if not text:
            return
        idx = len(chunks)
        chunks.append(
            {
                "chunk_id": f"{doc_id}__{idx:03d}",
                "doc_id": doc_id,
                "domain": domain,
                "section_index": idx,
                "title": cur_title,
                "text": text,
                "line_start": cur_start,
                "line_end": end_line,
            }
        )

    for i, line in enumerate(lines, 1):
        if line.startswith("## "):
            flush(i - 1)
            cur_title = line[3:].strip()
            cur_start = i
            buf = [line]
        else:
            buf.append(line)
    flush(len(lines))
    return chunks


def main() -> int:
    domains = json.loads((CORPUS / "domains.json").read_text(encoding="utf-8"))["domains"]
    all_chunks: list[dict] = []
    index: dict[str, dict] = {}
    counts: dict[str, int] = {}

    for domain, meta in sorted(domains.items()):
        if meta.get("status") != "active":
            continue
        ddir = CORPUS / domain
        if not ddir.is_dir():
            print(f"[跳过] {domain}: 无 corpus/{domain}/ 目录")
            continue
        for md in sorted(ddir.glob("*.md")):
            chunks = split_doc(md, domain)
            all_chunks.extend(chunks)
            counts[domain] = counts.get(domain, 0) + len(chunks)
            for c in chunks:
                index[c["chunk_id"]] = {
                    "doc_id": c["doc_id"],
                    "domain": c["domain"],
                    "title": c["title"],
                    "file": f"corpus/{domain}/{md.name}",
                    "line_start": c["line_start"],
                    "line_end": c["line_end"],
                }
        print(f"[切分] {domain}: {len(list(ddir.glob('*.md')))} 份文档 -> {counts[domain]} 个 chunk")

    OUT_CHUNKS.write_text(
        "\n".join(json.dumps(c, ensure_ascii=False) for c in all_chunks) + "\n",
        encoding="utf-8",
    )
    OUT_INDEX.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n共 {len(all_chunks)} 个 chunk   已写出 {OUT_CHUNKS.name} / {OUT_INDEX.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
