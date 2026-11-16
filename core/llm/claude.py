"""Claude 공급자 (anthropic SDK).

- 구조화 출력: output_config.format = json_schema (스키마는 strict_json_schema로 만든다)
- 거절(stop_reason=refusal)은 LLMRefusalError. 서버 측 fallbacks는 기본으로 켠다
  (LLM_CLAUDE_FALLBACKS=off 로 끌 수 있음). 모델명은 .env에서만 읽는다.
"""

from __future__ import annotations

import base64
import os

import anthropic

from core.llm.base import LLMError, LLMRefusalError, Part, T, Usage, parse_with_retry, strict_json_schema

FALLBACK_BETA = "server-side-fallback-2026-07-01"
MAX_TOKENS = 16000  # 비스트리밍 요청 기준


def _blocks(parts: list[Part]) -> list[dict]:
    """PDF·이미지는 원본 그대로, 텍스트는 text 블록. 문서 블록을 텍스트보다 앞에 둔다."""
    docs, texts = [], []
    for p in parts:
        if p.text is not None:
            texts.append({"type": "text", "text": p.text})
            continue
        data = base64.standard_b64encode(p.data).decode("ascii")
        if p.mime == "application/pdf":
            docs.append({"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": data}})
        else:
            docs.append({"type": "image", "source": {"type": "base64", "media_type": p.mime, "data": data}})
    return docs + texts


class ClaudeProvider:
    name = "claude"

    def __init__(self, model: str, api_key: str | None = None, client: anthropic.Anthropic | None = None):
        if not model:
            raise LLMError("LLM_MODEL_EXTRACT/LLM_MODEL_WRITE 에 Claude 모델명을 넣으세요(예: claude-opus-5-5).")
        self.model = model
        self.client = client or anthropic.Anthropic(api_key=api_key)
        self.fallbacks = (os.environ.get("LLM_CLAUDE_FALLBACKS") or "default").strip().lower() != "off"
        self.effort = (os.environ.get("LLM_EFFORT") or "").strip() or None

    def _create(self, system: str, content: list[dict], output_format: dict | None):
        output_config: dict = {}
        if output_format:
            output_config["format"] = output_format
        if self.effort:
            output_config["effort"] = self.effort
        kwargs = dict(model=self.model, max_tokens=MAX_TOKENS, system=system, messages=[{"role": "user", "content": content}])
        if output_config:
            kwargs["output_config"] = output_config
        try:
            if self.fallbacks:
                resp = self.client.beta.messages.create(betas=[FALLBACK_BETA], fallbacks="default", **kwargs)
            else:
                resp = self.client.messages.create(**kwargs)
        except anthropic.AuthenticationError as e:
            raise LLMError("Claude 인증 실패: ANTHROPIC_API_KEY를 확인하세요.") from e
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
        return text, resp.usage.input_tokens, resp.usage.output_tokens

    def generate_json(self, system: str, parts: list[Part], schema: type[T]) -> tuple[T, Usage]:
        usage = Usage(self.name, self.model)
        fmt = {"type": "json_schema", "schema": strict_json_schema(schema)}
        base = _blocks(parts)

        def call(hint: str | None):
            content = base + ([{"type": "text", "text": hint}] if hint else [])
            return self._create(system, content, fmt)

        return parse_with_retry(call, schema, usage), usage

    def generate_text(self, system: str, prompt: str) -> tuple[str, Usage]:
        usage = Usage(self.name, self.model)
        text, i, o = self._create(system, [{"type": "text", "text": prompt}], None)
        usage.input_tokens, usage.output_tokens = i, o
        return text, usage

