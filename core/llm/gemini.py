"""Gemini 공급자 (google-genai SDK).

- 구조화 출력: response_mime_type=application/json + response_json_schema
- PDF·이미지는 Part.from_bytes로 원본 그대로 넣는다. 모델명은 .env에서만 읽는다.
(google-genai 3.3.0의 실제 시그니처로 확인: models.generate_content(model, contents, config),
 usage_metadata.prompt_token_count / candidates_token_count)
"""

from __future__ import annotations

from google import genai
from google.genai import errors as genai_errors
from google.genai import types
from tenacity import Retrying, retry_if_exception, stop_after_attempt, wait_exponential

from core.llm.base import LLMError, LLMRefusalError, Part, T, Usage, parse_with_retry, strict_json_schema


MAX_ATTEMPTS = 3
RETRY_WAIT = wait_exponential(multiplier=2, min=2, max=20)  # 2, 4, 8초… 테스트에서 바꿀 수 있게 모듈 변수
REQUEST_TIMEOUT_MS = 180_000  # 실제 혼잡 시 추출(큰 스키마)이 90초 안에 끝나지 않아 504 DEADLINE_EXCEEDED가 났다


def _is_timeout(e: BaseException) -> bool:
    """HTTP 라이브러리 종류와 상관없이 시간 초과 예외인지(이름으로 판단)."""
    return any("Timeout" in t.__name__ for t in type(e).__mro__)


def _contents(parts: list[Part], hint: str | None = None) -> list:
    out = []
    for p in parts:
        if p.text is not None:
            out.append(types.Part.from_text(text=p.text))
        else:
            out.append(types.Part.from_bytes(data=p.data, mime_type=p.mime))
    if hint:
        out.append(types.Part.from_text(text=hint))
    return [types.Content(role="user", parts=out)]


class GeminiProvider:
    name = "gemini"

    def __init__(self, model: str, api_key: str | None = None, client: "genai.Client | None" = None):
        if not model:
            raise LLMError("LLM_MODEL_EXTRACT/LLM_MODEL_WRITE 에 Gemini 모델명을 넣으세요.")
        self.model = model
        # 요청당 시간 제한(밀리초). 실제 호출에서 응답 하나가 3분 넘게 걸린 적이 있어(혼잡 시) 끊고 다시 시도한다.
        self.client = client or genai.Client(api_key=api_key, http_options=types.HttpOptions(timeout=REQUEST_TIMEOUT_MS))

    def _generate(self, system: str, contents: list, json_schema: dict | None):
        config = types.GenerateContentConfig(
            system_instruction=system,
            response_mime_type="application/json" if json_schema else None,
            response_json_schema=json_schema,
        )
        # 실제 호출(2026-11-15)에서 503 UNAVAILABLE "high demand"가 나왔다 → 503·429는 지수 백오프로 다시 시도
        def retryable(e: BaseException) -> bool:
            return (
                isinstance(e, genai_errors.ServerError)
                or (isinstance(e, genai_errors.ClientError) and getattr(e, "code", None) == 429)
                or _is_timeout(e)
            )

        try:
            for attempt in Retrying(retry=retry_if_exception(retryable), stop=stop_after_attempt(MAX_ATTEMPTS), wait=RETRY_WAIT, reraise=True):
                with attempt:
                    resp = self.client.models.generate_content(model=self.model, contents=contents, config=config)
        except genai_errors.ClientError as e:
            code = getattr(e, "code", "?")
            hint = " (모델명 LLM_MODEL_EXTRACT/LLM_MODEL_WRITE 확인)" if code == 404 else " (GEMINI_API_KEY 확인)" if code in (401, 403) else ""
            raise LLMError(f"Gemini 요청 오류({code}){hint}") from e
        except genai_errors.ServerError as e:
            raise LLMError(f"Gemini 서버 오류({getattr(e, 'code', '?')}): 혼잡하거나 일시 장애입니다. 잠시 뒤 다시 시도하세요.") from e
        except Exception as e:
            if _is_timeout(e):
                raise LLMError(f"Gemini 응답 시간 초과({REQUEST_TIMEOUT_MS // 1000}초 × {MAX_ATTEMPTS}회). 잠시 뒤 다시 시도하세요.") from e
            raise
        cand = (resp.candidates or [None])[0]
        reason = str(getattr(cand, "finish_reason", "") or "")
        if "SAFETY" in reason or "PROHIBITED" in reason or "BLOCKLIST" in reason:
            raise LLMRefusalError(f"Gemini가 응답을 막았습니다({reason}).")
        if "MAX_TOKENS" in reason:
            raise LLMError("응답이 최대 토큰에서 잘렸습니다.")
        um = resp.usage_metadata
        return resp.text or "", int(getattr(um, "prompt_token_count", 0) or 0), int(getattr(um, "candidates_token_count", 0) or 0)

    def generate_json(self, system: str, parts: list[Part], schema: type[T]) -> tuple[T, Usage]:
        usage = Usage(self.name, self.model)
        js = strict_json_schema(schema)
        return parse_with_retry(lambda hint: self._generate(system, _contents(parts, hint), js), schema, usage), usage

    def generate_text(self, system: str, prompt: str) -> tuple[str, Usage]:
        usage = Usage(self.name, self.model)
        text, i, o = self._generate(system, _contents([Part.of_text(prompt)]), None)
        usage.input_tokens, usage.output_tokens = i, o
        return text, usage
