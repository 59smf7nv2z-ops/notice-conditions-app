"""LLM 사용량 기록: data/logs/llm_usage.csv

남기는 것: 시각, 공급자, 모델, 작업(analyze/classify/extract/template), 입력·출력 토큰, 캐시 읽기·쓰기 토큰,
재시도 수, 문서 해시, 비고(상위 모델 폴백 사유). 폴백하면 모델별로 한 줄씩 남긴다.
본문·주소·파일명은 남기지 않는다.
"""

from __future__ import annotations

import csv
import os
from datetime import datetime
from pathlib import Path

from core.llm.base import Usage

FIELDS = [
    "timestamp", "provider", "model", "task", "input_tokens", "output_tokens",
    "cache_read_tokens", "cache_write_tokens", "retries", "doc_hash", "note",
]
TASKS = ("analyze", "classify", "extract", "template")


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
    _upgrade_header(path)
    new = not path.exists()
    now = datetime.now().isoformat(timespec="seconds")
    with open(path, "a", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if new:
            w.writeheader()
        for u in usage.all():
            w.writerow(
                {
                    "timestamp": now,
                    "provider": u.provider,
                    "model": u.model,
                    "task": task,
                    "input_tokens": int(u.input_tokens),
                    "output_tokens": int(u.output_tokens),
                    "cache_read_tokens": int(u.cache_read_tokens),
                    "cache_write_tokens": int(u.cache_write_tokens),
                    "retries": int(u.retries),
                    "doc_hash": doc_hash,
                    "note": u.note[:200],
                }
            )


def _upgrade_header(path: Path) -> None:
    """예전 칸 구성의 로그 파일이면 새 칸을 빈 값으로 넣어 다시 쓴다(작은 파일)."""
    if not path.exists():
        return
    with open(path, encoding="utf-8", newline="") as f:
        header = next(csv.reader(f), None)
    if not header or header == FIELDS:
        return
    with open(path, encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in FIELDS})
