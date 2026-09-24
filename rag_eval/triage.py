"""错误归因：把答错的题定位到该改哪个组件（《检测RAG质量.md》§53-54, §60）。

    Retrieval Error   找不到      → 改 Embedding / BM25 / Hybrid
    Ranking Error     排名错      → 改 Reranker / Top-K
    Context Error     不完整/版本错 → 改 Chunking / Parent-doc / Filtering
    Generation Error  答错/幻觉   → 改 Prompt / LLM
    Citation Error    引用不支撑  → 改引用生成逻辑
    No-answer Error   该拒未拒    → 改拒答策略
    System Error      超时/异常   → 改工程稳定性

决策树按 §53 的 Step 1→5 顺序短路：

    error 非空                          → System
    ├─ expected_abstain 且未拒答         → No-answer（幻觉）
    ├─ expected_abstain 且拒答           → None（成功）
    ├─ 非无答案题却拒答                  → No-answer（误拒）
    └─ 答错？
       ├─ gt chunk 不在 retrieved       → Retrieval
       ├─ 在 retrieved 但没进 context    → Ranking（排名太靠后）
       ├─ 该进 context 却缺失/截断       → Context
       ├─ 证据齐全但引了非 gt 的 chunk   → Citation（版本/引用选错）
       ├─ 证据齐全且引用正常却答错       → Generation
       └─ 答对但引用了非 gt 的 chunk    → Citation

注意：校验器只管格式，这里才管对错。判定为错误不等于提交无效。
"""
from __future__ import annotations

import re
from enum import Enum

# 判定「gt chunk 是否进了 context」时，rank 不超过它就认为本该被拼进 prompt
CONTEXT_RANK_BUDGET = 5


class ErrorKind(str, Enum):
    NONE = "none"
    SYSTEM = "system_error"
    NO_ANSWER = "no_answer_error"
    RETRIEVAL = "retrieval_error"
    RANKING = "ranking_error"
    CONTEXT = "context_error"
    CITATION = "citation_error"
    GENERATION = "generation_error"


# 对应 §60 的「→ 建议优化组件」
ADVICE = {
    ErrorKind.RETRIEVAL: "Embedding / BM25 / Hybrid Search / Query Rewrite",
    ErrorKind.RANKING: "Reranker / Top-K / Score Filtering",
    ErrorKind.CONTEXT: "Chunking / Parent Document Retrieval / Context Assembly",
    ErrorKind.GENERATION: "Prompt / LLM / Context Order",
    ErrorKind.CITATION: "引用生成逻辑 / 版本消歧（时间元数据过滤）",
    ErrorKind.NO_ANSWER: "拒答策略（Abstention Prompt / 无答案阈值）",
    ErrorKind.SYSTEM: "工程稳定性（超时/重试/降级）",
    ErrorKind.NONE: "",
}

LABELS = {
    ErrorKind.NONE: "无错误",
    ErrorKind.SYSTEM: "System Error",
    ErrorKind.NO_ANSWER: "No-answer Error",
    ErrorKind.RETRIEVAL: "Retrieval Error",
    ErrorKind.RANKING: "Ranking Error",
    ErrorKind.CONTEXT: "Context Error",
    ErrorKind.CITATION: "Citation Error",
    ErrorKind.GENERATION: "Generation Error",
}


# ------------------------------------------------------------ 正确性判定

_NUM = re.compile(r"\d+(?:\.\d+)?")


def approx_correct(rec: dict, gt: dict) -> bool | None:
    """规则版正确性判定 —— P2 会换成 LLM Judge，这里只求 P1 能跑通。

    - 无答案题：拒答即正确
    - 有标准答案：标准答案里的每个数字都必须出现在回答里（抓版本混淆最有效）
    """
    if gt.get("expected_abstain"):
        return bool(rec.get("abstained"))
    answer = rec.get("answer") or ""
    if not answer.strip() or rec.get("error"):
        return False
    if rec.get("abstained"):
        return False
    expected = gt.get("ground_truth_answer") or ""
    nums = _NUM.findall(expected)
    if not nums:
        return None  # 无数字可锚定，规则判不了，留给 LLM Judge
    return all(n in answer for n in nums)


def citation_chunk_ids(rec: dict) -> set[str]:
    return {c.get("chunk_id") for c in (rec.get("citations") or []) if c.get("chunk_id")}


def gt_chunk_ids(gt: dict) -> set[str]:
    return {c.get("chunk_id") for c in (gt.get("ground_truth_chunks") or []) if c.get("chunk_id")}


def ranked_ids(rec: dict) -> list[str]:
    return [
        c.get("chunk_id")
        for c in sorted(rec.get("retrieved_chunks") or [], key=lambda c: c.get("rank", 0))
        if c.get("chunk_id")
    ]


def _norm(text: str) -> str:
    return re.sub(r"\s+", "", text or "")


def chunk_text(rec: dict, chunk_id: str) -> str | None:
    for c in rec.get("retrieved_chunks") or []:
        if c.get("chunk_id") == chunk_id:
            return c.get("text")
    return None


def in_context(rec: dict, chunk_id: str) -> bool | None:
    """gt chunk 是否真的进了送给 LLM 的 context。

    有 context 文本时用 chunk 文本做包含判定；拿不到文本则退回 rank 启发式。
    返回 None 表示无法判断（record 没给 context 字段）。
    """
    if not rec.get("context"):
        return None
    text = chunk_text(rec, chunk_id)
    if not text:
        return chunk_id in (rec.get("context") or "")
    ctx, body = _norm(rec["context"]), _norm(text)
    if not body:
        return None
    # 取一段有辨识度的窗口做包含判定，容忍前后截断
    window = body[:40] if len(body) >= 40 else body
    return window in ctx


# ------------------------------------------------------------ 决策树

def triage(
    rec: dict,
    gt: dict,
    is_correct: bool | None = None,
    citation_ok: bool | None = None,
) -> dict:
    """单条记录归因。返回 {kind, label, reason, advice, is_correct}。"""
    def out(kind: ErrorKind, reason: str) -> dict:
        return {
            "kind": kind.value,
            "label": LABELS[kind],
            "reason": reason,
            "advice": ADVICE[kind],
            "is_correct": is_correct,
        }

    # Step 0：超时/异常 —— 不进质量树，直接归工程问题
    if rec.get("error"):
        return out(ErrorKind.SYSTEM, f"执行失败: {rec['error']}")

    if is_correct is None:
        is_correct = approx_correct(rec, gt)

    gts, ranked = gt_chunk_ids(gt), ranked_ids(rec)
    cited = citation_chunk_ids(rec)
    cites_foreign = bool(cited) and not (cited & gts) if gts else False

    # Step 1：无答案题的拒答判定（§47）
    if gt.get("expected_abstain"):
        if rec.get("abstained"):
            return out(ErrorKind.NONE, "无答案题正确拒答")
        return out(
            ErrorKind.NO_ANSWER,
            "知识库无答案却给出实质回答（幻觉）；应答『根据现有知识库，无法找到相关信息』",
        )
    if rec.get("abstained"):
        return out(ErrorKind.NO_ANSWER, "知识库有答案却拒答（误拒）")

    # Step 2/3：检索与上下文 —— 即使答对了也记录诊断，供 Error Breakdown 用
    if is_correct:
        # §53 Step 5：答案对但引用错
        if citation_ok is False or cites_foreign:
            return out(ErrorKind.CITATION, "答案正确，但引用的 chunk 不支撑该论断")
        return out(ErrorKind.NONE, "答案正确")

    # —— 以下仅答错的题 ——
    if gts and not (set(ranked) & gts):
        return out(
            ErrorKind.RETRIEVAL,
            f"正确 chunk {sorted(gts)} 不在检索结果中（共返回 {len(ranked)} 条）",
        )

    hit = sorted(set(ranked) & gts)
    ranks = [ranked.index(cid) + 1 for cid in hit if cid in ranked]

    # 有没有进 context：拿不到 context 字段时退回 rank 启发式
    if rec.get("context") is None:
        entered = bool(ranks) and min(ranks) <= CONTEXT_RANK_BUDGET
    else:
        entered = any(in_context(rec, cid) for cid in hit)

    if not entered:
        if ranks and min(ranks) > CONTEXT_RANK_BUDGET:
            return out(
                ErrorKind.RANKING,
                f"正确 chunk {hit} 排在第 {min(ranks)} 位，未进入 Top-{CONTEXT_RANK_BUDGET} context"
                f"（改 Reranker / 调大 Top-K）",
            )
        return out(
            ErrorKind.CONTEXT,
            f"正确 chunk {hit} 已检索到（第 {min(ranks) if ranks else '?'} 位）但未拼进 context，"
            f"上下文组装/过滤丢掉了证据",
        )

    # 证据齐全仍答错
    if cites_foreign:
        foreign = sorted(cited - gts)
        return out(
            ErrorKind.CITATION,
            f"证据已进入 context，但引用指向了非标准答案的 chunk {foreign}"
            f"（典型版本混淆：改了引用/时间消歧，不必动检索）",
        )
    return out(
        ErrorKind.GENERATION,
        f"正确证据已在 context 中（chunk {hit}）却答错，属生成/推理问题",
    )


def triage_all(
    records: list[dict],
    gt_by_id: dict[str, dict],
    correctness: dict[tuple[str, str], bool] | None = None,
) -> list[dict]:
    """整场归因。correctness: {(question_id, system_name): is_correct}，缺的用规则补。"""
    correctness = correctness or {}
    out = []
    for rec in records:
        gt = gt_by_id.get(rec.get("question_id"))
        if gt is None:
            continue
        key = (rec.get("question_id"), rec.get("system_name"))
        out.append(
            {
                "question_id": rec.get("question_id"),
                "system_name": rec.get("system_name"),
                **triage(rec, gt, is_correct=correctness.get(key)),
            }
        )
    return out


def error_breakdown(items: list[dict]) -> dict[str, int]:
    """§54 的 Error Breakdown：按 kind 计数（none 不计）。"""
    counts: dict[str, int] = {}
    for it in items:
        kind = it.get("kind")
        if kind and kind != ErrorKind.NONE.value:
            counts[kind] = counts.get(kind, 0) + 1
    return counts
