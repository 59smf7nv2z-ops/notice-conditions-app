"""Claude 공급자 (anthropic SDK).

- 구조화 출력: output_config.format = json_schema (스키마는 strict_json_schema로 만든다)
- 출력 토큰 절약: 사고(thinking)를 끈다. 모델마다 끄는 방법이 다르다(_thinking_config).
  · Haiku 5.5 등: {"type": "disabled"} (effort high 이하에서만 허용)
  · Sonnet 5.5: disabled가 400 → {"type": "between_tools"} (도구를 안 쓰므로 사고 없음)
  · Opus 5.5·Fable: 끌 수 없음 → effort low로 줄인다
  LLM_THINKING=on 이면 끄지 않는다.
- 프롬프트 캐싱: 시스템 프롬프트 끝, 그리고 공고 본문의 마지막 조각(작업 지시 바로 앞)에 cache_control.
  분류 → 추출이 같은 시스템·본문을 쓰므로 추출 때 본문을 캐시로 읽는다(core.llm.extractor 참고).
- 거절(stop_reason=refusal)은 LLMRefusalError. 서버 측 fallbacks="default"는 지원하는 모델에서만 켠다
  (Haiku 5.5는 서버 측 폴백이 없고 목록을 보내면 400). 상위 모델로 다시 하기는 core.llm.fallback.
- 모델명은 .env에서만 읽는다. "Claude-Haiku-5.5"처럼 써도 API 이름(claude-haiku-5-5)으로 바꾼다.
"""

from __future__ import annotations

import base64
import os
import re

import anthropic

from core.llm.base import LLMError, LLMRefusalError, Part, T, Usage, compact_json_schema, from_compact, parse_with_retry

FALLBACK_BETA = "server-side-fallback-2026-07-01"
SERVER_FALLBACK_MODELS = ("claude-fable-", "claude-mythos-", "claude-opus-5", "claude-sonnet-5-5")
MAX_TOKENS = 16000  # 비스트리밍 요청 기준. 출력은 JSON뿐이라 실제로는 수천 토큰 이하
CACHE = {"type": "ephemeral"}


class LLMConfigError(LLMError):
    """설정 문제(키·모델명). 상위 모델로 다시 하지 않고 바로 알린다(틀린 모델명이 비싼 모델로 조용히 넘어가지 않게)."""


class LLMAuthError(LLMConfigError):
    """키 문제."""


def normalize_model(name: str) -> str:
    """'Claude-Haiku-5.5', 'claude haiku 5.5' → 'claude-haiku-5-5'. 이미 API 이름이면 그대로."""
    s = re.sub(r"[\s_]+", "-", name.strip().lower())
    s = re.sub(r"(?<=\d)\.(?=\d)", "-", s)
    return s


def _thinking_config(model: str, effort: str | None) -> tuple[dict | None, str | None]:
    """(thinking 파라미터, effort). 사고를 끄면 출력 토큰(사고분)이 안 나간다."""
    if (os.environ.get("LLM_THINKING") or "").strip().lower() in ("on", "adaptive"):
        return {"type": "adaptive"}, effort
    if model.startswith(("claude-opus-5-5", "claude-fable-", "claude-mythos-")):
        return None, effort or "low"  # 끌 수 없는 모델: 생략 + 낮은 effort
    if model.startswith("claude-sonnet-5-5"):
        return {"type": "between_tools"}, effort if effort in (None, "low", "medium", "high") else "high"
    return {"type": "disabled"}, effort if effort in (None, "low", "medium", "high") else "high"


def _blocks(parts: list[Part]) -> list[dict]:
    """조각 순서를 그대로 지킨다([파일: 이름] 표시 → 그 파일의 이미지).

    마지막 조각이 작업 지시이고 그 앞이 공고 본문이면, 본문 마지막 블록에 cache_control을 붙인다.
    """
    out: list[dict] = []
    for p in parts:
        if p.text is not None:
            out.append({"type": "text", "text": p.text})
            continue
        data = base64.standard_b64encode(p.data).decode("ascii")
        kind = "document" if p.mime == "application/pdf" else "image"
        out.append({"type": kind, "source": {"type": "base64", "media_type": p.mime, "data": data}})
    if len(out) >= 2:
        out[-2] = {**out[-2], "cache_control": CACHE}
    return out


class ClaudeProvider:
    name = "claude"

    def __init__(self, model: str, api_key: str | None = None, client: anthropic.Anthropic | None = None):
        if not model:
            raise LLMError("LLM_MODEL_EXTRACT/LLM_MODEL_WRITE 에 Claude 모델명을 넣으세요(예: claude-haiku-5-5).")
        self.model = normalize_model(model)
        self.client = client or anthropic.Anthropic(api_key=api_key)
        self.server_fallbacks = (
            (os.environ.get("LLM_CLAUDE_FALLBACKS") or "default").strip().lower() != "off"
            and self.model.startswith(SERVER_FALLBACK_MODELS)
        )
        self.thinking, self.effort = _thinking_config(self.model, (os.environ.get("LLM_EFFORT") or "").strip() or None)

    def _create(self, system: str, content: list[dict], output_format: dict | None):
        output_config: dict = {}
        if output_format:
            output_config["format"] = output_format
        if self.effort:
            output_config["effort"] = self.effort
        kwargs = dict(
            model=self.model,
            max_tokens=MAX_TOKENS,
            system=[{"type": "text", "text": system, "cache_control": CACHE}],
            messages=[{"role": "user", "content": content}],
        )
        if output_config:
            kwargs["output_config"] = output_config
        if self.thinking:
            kwargs["thinking"] = self.thinking
        try:
            if self.server_fallbacks:
                resp = self.client.beta.messages.create(betas=[FALLBACK_BETA], fallbacks="default", **kwargs)
            else:
                resp = self.client.messages.create(**kwargs)
        except anthropic.AuthenticationError as e:
            raise LLMAuthError("Claude 인증 실패: ANTHROPIC_API_KEY를 확인하세요.") from e
        except anthropic.PermissionDeniedError as e:
            raise LLMAuthError(f"Claude 권한 없음: {e.message}") from e
        except anthropic.NotFoundError as e:
            raise LLMConfigError(f"Claude 모델 '{self.model}'을 찾지 못했습니다(.env LLM_MODEL_* 확인).") from e
        except anthropic.BadRequestError as e:
            raise LLMError(f"Claude 요청 오류: {e.message}") from e
        except anthropic.RateLimitError as e:
            raise LLMError("Claude 호출 한도 초과. 잠시 뒤 다시 시도하세요.") from e
        except anthropic.APIStatusError as e:
            raise LLMError(f"Claude 서버 오류({e.status_code})") from e
        except anthropic.APIConnectionError as e:
            raise LLMError("Claude 연결 실패") from e
        if resp.stop_reason == "refusal":
            raise LLMRefusalError("Claude가 요청을 거절했습니다.")
        if resp.stop_reason == "max_tokens":
            raise LLMError("응답이 max_tokens에서 잘렸습니다.")
        text = next((b.text for b in resp.content if b.type == "text"), "")
        u = resp.usage
        return (
            text,
            int(u.input_tokens or 0),
            int(u.output_tokens or 0),
            int(getattr(u, "cache_read_input_tokens", 0) or 0),
            int(getattr(u, "cache_creation_input_tokens", 0) or 0),
        )

    def generate_json(self, system: str, parts: list[Part], schema: type[T]) -> tuple[T, Usage]:
        usage = Usage(self.name, self.model)
        # Claude 구조화 출력 한도(null 허용 16개, 문법 크기) 때문에 작은 모양으로 받고 되돌린다(base.compact_json_schema)
        fmt = {"type": "json_schema", "schema": compact_json_schema(schema)}
        base = _blocks(parts)

        def call(hint: str | None):
            content = base + ([{"type": "text", "text": hint}] if hint else [])
            return self._create(system, content, fmt)

        return parse_with_retry(call, schema, usage, transform=lambda raw: from_compact(raw, schema)), usage

    def generate_text(self, system: str, prompt: str) -> tuple[str, Usage]:
        usage = Usage(self.name, self.model)
        text, *tokens = self._create(system, [{"type": "text", "text": prompt}], None)
        usage.add(tokens)
        return text, usage
