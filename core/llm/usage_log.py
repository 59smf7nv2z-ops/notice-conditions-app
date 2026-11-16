"""LLM 사용량 기록: data/logs/llm_usage.csv

남기는 것: 시각, 공급자, 모델, 작업(classify/extract/template), 입력·출력 토큰, 재시도 수, 문서 해시.
본문·주소·파일명은 남기지 않는다.
"""

from __future__ import annotations

import csv
import os
from datetime import datetime
from pathlib import Path

from core.llm.base import Usage

FIELDS = ["timestamp", "provider", "model", "task", "input_tokens", "output_tokens", "retries", "doc_hash"]
TASKS = ("classify", "extract", "template")


def log_path() -> Path:
    override = os.environ.get("LLM_USAGE_LOG")
    return Path(override) if override else Path(__file__).resolve().parents[2] / "data" / "logs" / "llm_usage.csv"


def record(usage: Usage, task: str, doc_hash: str) -> None:
    if task not in TASKS:
        raise ValueError(f"알 수 없는 작업: {task}")
    if not (len(doc_hash) == 16 and all(c in "0123456789abcdef" for c in doc_hash)):
        raise ValueError("doc_hash는 16자리 16진수여야 합니다(본문을 넣지 않기 위해 형식을 강제).")
    path = log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    new = not path.exists()
    with open(path, "a", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if new:
            w.writeheader()
        w.writerow(
            {
                "timestamp": datetime.now().isoformat(timespec="seconds"),
                "provider": usage.provider,
                "model": usage.model,
                "task": task,
                "input_tokens": int(usage.input_tokens),
                "output_tokens": int(usage.output_tokens),
                "retries": int(usage.retries),
                "doc_hash": doc_hash,
            }
        )
