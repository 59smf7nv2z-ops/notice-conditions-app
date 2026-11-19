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
    input_tokens: int = 0  # 캐시를 쓰지 않은 입력
    output_tokens: int = 0
    retries: int = 0
    cache_read_tokens: int = 0  # 캐시에서 읽은 입력(입력 단가의 약 0.1배)
    cache_write_tokens: int = 0  # 캐시에 새로 쓴 입력(약 1.25배)
    note: str = ""  # 예: 상위 모델 폴백 사유
    previous: list["Usage"] = field(default_factory=list)  # 폴백 전에 쓴 모델의 사용량

    def add(self, tokens: tuple) -> None:
        """(입력, 출력[, 캐시읽기, 캐시쓰기]) 누적."""
        self.input_tokens += tokens[0]
        self.output_tokens += tokens[1]
        if len(tokens) > 2:
            self.cache_read_tokens += tokens[2]
            self.cache_write_tokens += tokens[3]

    def all(self) -> list["Usage"]:
        """폴백 전 사용량까지 시간 순서로."""
        return [*self.previous, self]

    @property
    def total_input(self) -> int:
        return sum(u.input_tokens + u.cache_read_tokens + u.cache_write_tokens for u in self.all())

    @property
    def total_output(self) -> int:
        return sum(u.output_tokens for u in self.all())


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
    call,  # (extra_user_text: str | None) -> (raw_json_text, input_tokens, output_tokens[, cache_read, cache_write])
    schema: type[T],
    usage: Usage,
    transform=None,  # 원문 JSON 텍스트 → 검증 전 변환(예: restore_nulls)
) -> T:
    """원문 JSON을 pydantic으로 검증. 실패하면 오류 메시지를 붙여 1회 재시도, 그래도 실패하면 원문과 함께 예외."""

    def validate(raw: str) -> T:
        if transform is not None:
            try:
                raw = transform(raw)
            except ValueError as e:  # JSON이 아님 → 검증 오류와 같게 다룬다
                return schema.model_validate_json(raw if raw.strip() else "{}")
        return schema.model_validate_json(raw)

    raw, *tokens = call(None)
    usage.add(tokens)
    try:
        return validate(raw)
    except ValidationError as e:
        first_error = e
    usage.retries += 1
    hint = (
        "직전 응답이 스키마 검증을 통과하지 못했습니다. 아래 오류를 고쳐 같은 스키마로 다시 답하세요.\n"
        + json.dumps(first_error.errors(include_url=False, include_input=False), ensure_ascii=False, default=str)[:2000]
    )
    raw2, *tokens = call(hint)
    usage.add(tokens)
    try:
        return validate(raw2)
    except ValidationError as e:
        raise LLMValidationError(f"스키마 검증 실패(재시도 후): {e.error_count()}개 오류", raw2) from e


# Claude 구조화 출력은 null 허용(anyOf/type 배열) 항목이 16개까지다. 추출 스키마는 49개라 400이 난다
# (2026-11-17 실호출 확인) → Claude에는 null 대신 빈 값(문자열 "", 정수 0, 참거짓 "unknown")을 받고
# restore_nulls로 null로 되돌린다.
NULL_STR, NULL_INT, NULL_BOOL = "", 0, "unknown"


def _null_branch(node: dict) -> dict | None:
    """{"anyOf": [X, {"type": "null"}]} 이면 X, 아니면 None."""
    opts = node.get("anyOf")
    if isinstance(opts, list) and len(opts) == 2 and {"type": "null"} in opts:
        return next(o for o in opts if o != {"type": "null"})
    return None


def strict_json_schema(model: type[BaseModel], nullable: bool = True) -> dict:
    """pydantic 스키마 → 구조화 출력용 JSON 스키마.

    모든 object에 additionalProperties=false·required 전체, 지원하지 않는 제약(min/max 등)과 default·title 제거,
    $defs는 펼친다. nullable=False면 null 허용 항목을 빈 값 규칙(NULL_*)으로 바꾼다.
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
            inner = None if nullable else _null_branch(node)
            if inner is not None:
                t = walk(dict(inner))
                kind = t.get("type")
                if kind == "string":
                    return {**t, "description": "원문에 없으면 빈 문자열"}
                if kind == "integer":
                    return {**t, "description": "원문에 없으면 0"}
                if kind == "boolean":
                    return {"type": "string", "enum": ["true", "false", NULL_BOOL], "description": "원문에 없거나 애매하면 unknown"}
                # 그 밖의 모양은 그대로 둔다(예상하지 않음)
            out = {k: walk(v) for k, v in node.items() if k not in drop}
            if out.get("type") == "object" and "properties" in out:
                out["additionalProperties"] = False
                out["required"] = list(out["properties"])
            return out
        if isinstance(node, list):
            return [walk(x) for x in node]
        return node

    return walk(schema)


def _pair_fields(schema: dict) -> list[str]:
    """{value, evidence} 모양 항목 이름(StrField·IntField 등)."""
    return [
        k for k, v in schema.get("properties", {}).items()
        if v.get("type") == "object" and set(v.get("properties", {})) == {"value", "evidence"}
    ]


def compact_json_schema(model: type[BaseModel]) -> dict:
    """Claude용 작은 스키마. 항목마다 {value, evidence} 객체를 두면 문법이 너무 커서 400이 난다(2026-11-17 확인).

    → 값은 위쪽에 바로 두고, 근거는 채운 항목만 evidence 목록에 [{field, quote}]로 받는다(출력 토큰도 줄어듦).
    null 허용 항목은 빈 값 규칙(NULL_*). 되돌리기는 from_compact.
    """
    full = strict_json_schema(model, nullable=False)
    pairs = _pair_fields(full)
    if not pairs:
        return full
    props = {k: (v["properties"]["value"] if k in pairs else v) for k, v in full["properties"].items()}
    props["evidence"] = {
        "type": "array",
        "description": "값을 채운 항목마다 원문 핵심 구절(60자 이내)",
        "items": {
            "type": "object",
            "additionalProperties": False,
            "required": ["field", "quote"],
            "properties": {"field": {"type": "string", "enum": pairs}, "quote": {"type": "string"}},
        },
    }
    return {"type": "object", "additionalProperties": False, "required": list(props), "properties": props}


def from_compact(raw: str, model: type[BaseModel]) -> str:
    """compact_json_schema로 받은 JSON → 원래 모델 모양(JSON 텍스트)."""
    data = json.loads(raw)
    pairs = _pair_fields(strict_json_schema(model))
    if pairs and isinstance(data, dict):
        quotes: dict[str, str] = {}
        for item in data.pop("evidence", None) or []:
            if isinstance(item, dict) and item.get("field") in pairs and item.get("quote"):
                f = item["field"]
                quotes[f] = f"{quotes[f]} / {item['quote']}" if f in quotes else item["quote"]
        for k in pairs:
            data[k] = {"value": data.get(k), "evidence": quotes.get(k) or NULL_STR}
    return restore_nulls(json.dumps(data, ensure_ascii=False), model)


def restore_nulls(raw: str, model: type[BaseModel]) -> str:
    """strict_json_schema(nullable=False)로 받은 JSON의 빈 값을 원래 스키마의 null로 되돌린다."""
    data = json.loads(raw)
    schema = model.model_json_schema()
    defs = schema.get("$defs", {})

    def resolve(node: dict) -> dict:
        while "$ref" in node:
            node = defs[node["$ref"].split("/")[-1]]
        return node

    def fix(value, node):
        node = resolve(node)
        inner = _null_branch(node)
        if inner is not None:
            inner = resolve(inner)
            kind = inner.get("type")
            if kind == "string" and value == NULL_STR:
                return None
            if kind == "integer" and value == NULL_INT:
                return None
            if kind == "boolean":
                return {"true": True, "false": False}.get(value, None) if isinstance(value, str) else value
            node = inner
        if isinstance(value, dict) and "properties" in node:
            return {k: fix(v, node["properties"].get(k, {})) for k, v in value.items()}
        if isinstance(value, list) and "items" in node:
            return [fix(v, node["items"]) for v in value]
        return value

    return json.dumps(fix(data, schema), ensure_ascii=False)


def usage_summary(usages: list["Usage | None"]) -> str:
    """화면 표시용 한 줄: 토큰 합계(캐시 포함), 실제로 답한 모델, 폴백 사유."""
    us = [x for u in usages if u for x in u.all()]
    if not us:
        return ""
    fresh = sum(u.input_tokens for u in us)
    read = sum(u.cache_read_tokens for u in us)
    write = sum(u.cache_write_tokens for u in us)
    out = sum(u.output_tokens for u in us)
    text = f"토큰 입력 {fresh + read + write:,}"
    if read or write:
        text += f"(캐시 읽기 {read:,}·쓰기 {write:,})"
    text += f" / 출력 {out:,}"
    notes = [u.note for u in usages if u and u.note]
    if notes:
        text += " · 상위 모델로 다시 함: " + "; ".join(notes)
    return text
