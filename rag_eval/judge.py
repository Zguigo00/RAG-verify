"""LLM-as-a-Judge 客户端（OpenAI 兼容协议）。

走 /v1/chat/completions，任何兼容端点都可用：DeepSeek / Qwen / Moonshot / vLLM / Ollama 等。
只用标准库 urllib，不增加第三方依赖。

设计要点（《检测RAG质量.md》§48-50）：
- 温度 0：判定要可复现
- 强制 JSON 输出 + 容错解析 + 失败重试：LLM 偶尔会包 markdown 代码块或加废话
- 每条样本跑 n 次取中位分：降方差，同时保留全部原始分供 Dashboard 显示置信度
- 3 分阈值二值化：>=4 判为正例（4=基本有证据、5=完全有证据），<=3 判为负例

环境变量（也可用构造参数覆盖）：
    RAG_JUDGE_BASE_URL  例如 https://api.deepseek.com/v1
    RAG_JUDGE_API_KEY
    RAG_JUDGE_MODEL     例如 deepseek-chat
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from typing import Any

DEFAULT_TIMEOUT = 90
DEFAULT_RETRIES = 3
DEFAULT_SAMPLES = 3
# 二值化阈值：score >= 4 视为「达标」。校准时与人工的 0/1 对齐用。
BINARY_THRESHOLD = 4


class JudgeError(RuntimeError):
    pass


def _extract_json(text: str) -> dict:
    """从模型输出里抠出 JSON 对象，容忍 markdown 代码块与前后废话。"""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise JudgeError(f"输出中找不到 JSON 对象: {text[:200]!r}")
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError as e:
        raise JudgeError(f"JSON 解析失败: {e}: {text[start:end+1][:200]!r}") from e


def _validate(payload: dict) -> dict:
    """校验返回结构：score 必须是 1-5 的整数。"""
    if "score" not in payload:
        raise JudgeError(f"缺少 score 字段: {payload}")
    try:
        score = int(payload["score"])
    except (TypeError, ValueError) as e:
        raise JudgeError(f"score 不是整数: {payload.get('score')!r}") from e
    if not 1 <= score <= 5:
        raise JudgeError(f"score 超出 1-5 范围: {score}")
    return {
        "score": score,
        "evidence": str(payload.get("evidence", "")),
        "reason": str(payload.get("reason", "")),
    }


class JudgeClient:
    """OpenAI 兼容 chat/completions 封装。"""

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        temperature: float = 0.0,
        timeout: int = DEFAULT_TIMEOUT,
        retries: int = DEFAULT_RETRIES,
        samples: int = DEFAULT_SAMPLES,
    ):
        self.base_url = (
            base_url or os.environ.get("RAG_JUDGE_BASE_URL") or "https://api.deepseek.com/v1"
        ).rstrip("/")
        self.api_key = api_key or os.environ.get("RAG_JUDGE_API_KEY") or ""
        self.model = model or os.environ.get("RAG_JUDGE_MODEL") or "deepseek-chat"
        self.temperature = temperature
        self.timeout = timeout
        self.retries = retries
        self.samples = samples
        self.calls = 0  # 记账：估算成本用

    # ------------------------------------------------------------ 单次调用

    def chat(self, prompt: str) -> str:
        body = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": self.temperature,
            # 尽量强制 JSON；不支持的服务端会忽略，靠 _extract_json 兜底
            "response_format": {"type": "json_object"},
        }
        req = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                **({"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}),
            },
            method="POST",
        )
        last: Exception | None = None
        for attempt in range(1, self.retries + 1):
            try:
                self.calls += 1
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                return data["choices"][0]["message"]["content"]
            except urllib.error.HTTPError as e:
                detail = e.read().decode("utf-8", "replace")[:300]
                last = JudgeError(f"HTTP {e.code}: {detail}")
                # 4xx（除 429）重试无意义
                if e.code < 500 and e.code != 429:
                    raise last
            except (urllib.error.URLError, TimeoutError, KeyError, json.JSONDecodeError) as e:
                last = JudgeError(f"{type(e).__name__}: {e}")
            time.sleep(min(2 ** attempt, 8))
        raise JudgeError(f"重试 {self.retries} 次后仍失败: {last}")

    def judge_once(self, prompt: str) -> dict:
        return _validate(_extract_json(self.chat(prompt)))

    # ------------------------------------------------------------ 降方差

    def judge(self, prompt: str, samples: int | None = None) -> dict:
        """跑 n 次取中位分，保留全部原始分。

        返回 {score, evidence, reason, scores, n, spread}：
        score 用于聚合；spread = max-min，Dashboard 用它提示「这条判分不稳，建议人工复核」。
        """
        n = samples if samples is not None else self.samples
        results = [self.judge_once(prompt) for _ in range(max(1, n))]
        scores = [r["score"] for r in results]
        scores_sorted = sorted(scores)
        median = scores_sorted[len(scores_sorted) // 2]
        # reason/evidence 取与中位分最接近的那次，保证解释与分数自洽
        pick = min(results, key=lambda r: abs(r["score"] - median))
        return {
            "score": median,
            "evidence": pick["evidence"],
            "reason": pick["reason"],
            "scores": scores,
            "n": len(scores),
            "spread": max(scores) - min(scores),
        }


def to_binary(score: float, threshold: int = BINARY_THRESHOLD) -> int:
    """1-5 分二值化为 0/1，供 Cohen's κ 与人工标注对齐。"""
    return int(score >= threshold)


def to_unit(score: float) -> float:
    """1-5 分归一化到 0-1，跨指标可比（进雷达图/加权滑块用）。"""
    return (float(score) - 1.0) / 4.0
