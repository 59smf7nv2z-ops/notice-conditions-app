"""LLM 공급자 공통 인터페이스.

LLM은 (a) 공고문 → 조건표 JSON 추출, (b) 사업유형 분류, (c) 안내문 '틀' 작성에만 쓴다.
건물 단위 데이터(주소, 대장 행)는 절대 넣지 않는다.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Protocol, TypeVar

from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)

SUPPORTED_MIME = ("application/pdf", "image/png", "image/jpeg")


@dataclass(frozen=True)
class Part:
    """요청 한 조각: 텍스트 또는 (bytes, mime)."""

    text: str | None = None
    data: bytes | None = None
    mime: str | None = None
    name: str = ""  # 원본 파일명(로그에는 남기지 않음)

    def __post_init__(self) -> None:
        if (self.text is None) == (self.data is None):
            raise ValueError("Part는 text 또는 data 중 하나만 가져야 합니다.")
        if self.data is not None and self.mime not in SUPPORTED_MIME:
            raise ValueError(f"지원하지 않는 형식: {self.mime} (허용: {SUPPORTED_MIME})")

    @classmethod
    def of_text(cls, text: str, name: str = "") -> "Part":
        return cls(text=text, name=name)

    @classmethod
    def of_bytes(cls, data: bytes, mime: str, name: str = "") -> "Part":
        return cls(data=data, mime=mime, name=name)


@dataclass
class Usage:
    provider: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    retries: int = 0


class LLMError(RuntimeError):
    pass


class LLMValidationError(LLMError):
    """스키마 검증이 재시도 후에도 실패했다. raw에 모델 원문을 담는다."""

    def __init__(self, message: str, raw: str):
        super().__init__(message)
        self.raw = raw


class LLMRefusalError(LLMError):
    """모델이 요청을 거절했다(stop_reason=refusal 등)."""


class LLMProvider(Protocol):
    name: str
    model: str

    def generate_json(self, system: str, parts: list[Part], schema: type[T]) -> tuple[T, Usage]: ...

    def generate_text(self, system: str, prompt: str) -> tuple[str, Usage]: ...


def doc_hash(parts: list[Part]) -> str:
    """사용량 로그용 문서 해시(본문 대신)."""
    h = hashlib.sha256()
    for p in parts:
        h.update(p.text.encode("utf-8") if p.text is not None else p.data or b"")
    return h.hexdigest()[:16]


def parse_with_retry(
    call,  # (extra_user_text: str | None) -> (raw_json_text, input_tokens, output_tokens)
    schema: type[T],
    usage: Usage,
) -> T:
    """원문 JSON을 pydantic으로 검증. 실패하면 오류 메시지를 붙여 1회 재시도, 그래도 실패하면 원문과 함께 예외."""
    raw, i, o = call(None)
    usage.input_tokens += i
    usage.output_tokens += o
    try:
        return schema.model_validate_json(raw)
    except ValidationError as e:
        first_error = e
    usage.retries += 1
    hint = (
        "직전 응답이 스키마 검증을 통과하지 못했습니다. 아래 오류를 고쳐 같은 스키마로 다시 답하세요.\n"
        + json.dumps(first_error.errors(include_url=False, include_input=False), ensure_ascii=False, default=str)[:2000]
    )
    raw2, i, o = call(hint)
    usage.input_tokens += i
    usage.output_tokens += o
    try:
        return schema.model_validate_json(raw2)
    except ValidationError as e:
        raise LLMValidationError(f"스키마 검증 실패(재시도 후): {e.error_count()}개 오류", raw2) from e


def strict_json_schema(model: type[BaseModel]) -> dict:
    """pydantic 스키마 → 구조화 출력용 JSON 스키마.

    모든 object에 additionalProperties=false·required 전체, 지원하지 않는 제약(min/max 등)과 default·title 제거,
    $defs는 펼친다.
    """
    schema = model.model_json_schema()
    defs = schema.pop("$defs", {})
    drop = {"default", "title", "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum",
            "minLength", "maxLength", "multipleOf", "pattern", "format", "examples"}

    def walk(node):
        if isinstance(node, dict):
            if "$ref" in node:
                ref = node["$ref"].split("/")[-1]
                return walk(dict(defs[ref]))
            out = {k: walk(v) for k, v in node.items() if k not in drop}
            if out.get("type") == "object" and "properties" in out:
                out["additionalProperties"] = False
                out["required"] = list(out["properties"])
            return out
        if isinstance(node, list):
            return [walk(x) for x in node]
        return node

    return walk(schema)
