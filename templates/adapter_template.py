#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""RAG 评测接入模板 —— 参赛方唯一要改的文件。

用法:
    python adapter_template.py --dataset dataset.jsonl --out run_log.jsonl

你只需要实现下面 3 个 TODO（把你的 RAG 接进来），其余保持不动。
本文件只用标准库，不需要安装任何第三方包。
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

SYSTEM_NAME = "team-A"  # TODO(0): 改成你的系统名，字母/数字/下划线/中划线


# ============================================================ TODO(1) 你的 RAG 接入点
def ask(question: str) -> dict:
    """跑你的 RAG，返回一条答题卡记录的内容。

    必须返回:
        answer: str          最终答案（超时/异常填 "" 并在 error 里写原因）
        abstained: bool      是否拒答（知识库无答案时应为 True）

    强烈建议返回（给了才能评对应指标，缺了就显示 N/A，不会算 0 分）:
        retrieved_chunks: list  检索到的 chunk，按最终排序（重排后）
                              [{"chunk_id":..., "doc_id":..., "rank":1, "score":0.87, "text":...}, ...]
                              chunk_id 必须用主办方发的那套编号，否则检索指标算不出来
        context: str            拼接后真正送给 LLM 的完整上下文
        citations: list         [{"claim": 答案里的某句话, "chunk_id": 支撑它的 chunk}, ...]
        latency_ms: int|float   端到端耗时
        input_tokens / output_tokens / cost_usd
        query_rewritten: str    改写后的检索 query（用于 debug）
        trace: dict             分阶段耗时 {"embedding_ms":45, "search_ms":80, ...}

    出错时:
        return {"answer": "", "abstained": False, "error": "timeout: xxx"}
    """
    # ---- 下面换成你自己的调用。三种典型写法: ----

    # (a) 直接调函数
    # r = my_rag_chain.invoke(question)

    # (b) 调本地 HTTP 服务
    # r = requests.post("http://127.0.0.1:8000/ask", json={"question": question}, timeout=30).json()

    # (c) 调 OpenAI 兼容接口 + 自己的检索
    # ctx = my_retriever.search(question, top_k=5)
    # r = {"answer": my_llm.chat(question, ctx), "retrieved_chunks": ctx, "context": format(ctx)}

    raise NotImplementedError("请把你的 RAG 调用写在这里")
    # return {...}


# ============================================================ TODO(2) 字段映射（可选）
def to_record(question_id: str, raw: dict) -> dict:
    """把你的返回值映射成标准答题卡字段。名字对得上就不用改。"""
    return {
        "system_name": SYSTEM_NAME,
        "question_id": question_id,
        "answer": raw.get("answer", ""),
        "abstained": bool(raw.get("abstained", False)),
        "query_rewritten": raw.get("query_rewritten"),
        "retrieved_chunks": [
            {
                "chunk_id": c.get("chunk_id") or c.get("id"),
                "doc_id": c.get("doc_id") or c.get("doc") or c.get("source"),
                "rank": i + 1,  # TODO(3): 如果你的返回里已有最终 rank，改成 c["rank"]
                "score": c.get("score"),
                "text": c.get("text") or c.get("content") or c.get("page_content"),
            }
            for i, c in enumerate(raw.get("retrieved_chunks") or raw.get("chunks") or [])
        ],
        "context": raw.get("context"),
        "citations": raw.get("citations"),
        "latency_ms": raw.get("latency_ms"),
        "input_tokens": raw.get("input_tokens"),
        "output_tokens": raw.get("output_tokens"),
        "cost_usd": raw.get("cost_usd"),
        "trace": raw.get("trace"),
        "error": raw.get("error"),
    }

# ============================================================ 主流程（不用改）
def main() -> int:
    ap = argparse.ArgumentParser(description="导出 RAG 评测答题卡 run_log.jsonl")
    ap.add_argument("--dataset", required=True, help="主办方发的 dataset.jsonl")
    ap.add_argument("--out", default="run_log.jsonl", help="输出文件（就是你要交的答题卡）")
    ap.add_argument("--limit", type=int, default=0, help="只跑前 N 题（调试用，0=全跑）")
    args = ap.parse_args()

    rows = []
    with open(args.dataset, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    if args.limit:
        rows = rows[: args.limit]
    print(f"共 {len(rows)} 题")

    out = Path(args.out)
    with out.open("w", encoding="utf-8") as f:
        for i, row in enumerate(rows, 1):
            qid, question = row["question_id"], row["question"]
            t0 = time.perf_counter()
            try:
                raw = ask(question)
            except Exception as e:  # 单题失败不应中断整场评测
                raw = {"answer": "", "abstained": False,
                       "error": f"{type(e).__name__}: {e}"}
            rec = to_record(qid, raw)
            if rec.get("latency_ms") is None:
                rec["latency_ms"] = round((time.perf_counter() - t0) * 1000, 1)
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            flag = "TIMEOUT" if rec.get("error") else ("拒答" if rec["abstained"] else "作答")
            print(f"[{i}/{len(rows)}] {qid}  {flag}  {rec['latency_ms']}ms")

    print(f"\n已写出 {out}  —— 请先自查再提交:")
    print(f"  python -m rag_eval.cli validate --dataset {args.dataset} --run-log {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
