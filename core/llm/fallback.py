"""기본 모델이 실패하거나 확신이 낮으면 상위 모델(.env LLM_MODEL_FALLBACK, 예: claude-sonnet-5-5)로 한 번 더 한다.

다시 하는 경우
- 오류: 스키마 검증 실패(재시도 후), 거절, 응답 잘림, 서버·연결 오류. 단 키·모델명 문제(LLMConfigError)는 바로 알린다.
- 결과: 출력 스키마의 fallback_reason()이 사유를 돌려줄 때(confidence=low, 핵심 조건 전무 등. core.llm.schemas).
상위 모델 결과를 그대로 쓴다(두 결과를 섞지 않는다). 사용량은 두 모델을 따로 남긴다(Usage.previous).
"""

from __future__ import annotations

from core.llm.base import LLMError, Part, T, Usage
from core.llm.claude import LLMConfigError


class FallbackProvider:
    def __init__(self, primary, fallback):
        self.primary = primary
        self.fallback = fallback
        self.name = primary.name
        self.model = primary.model

    def generate_json(self, system: str, parts: list[Part], schema: type[T]) -> tuple[T, Usage]:
        try:
            out, usage = self.primary.generate_json(system, parts, schema)
        except LLMConfigError:
            raise
        except LLMError as e:
            reason, first = f"{self.primary.model} 실패: {e}", Usage(self.primary.name, self.primary.model)
        else:
            check = getattr(out, "fallback_reason", None)
            reason = check() if callable(check) else None
            if not reason:
                return out, usage
            first = usage
        out2, usage2 = self.fallback.generate_json(system, parts, schema)
        usage2.previous = first.all()
        usage2.note = f"{self.primary.model} → {self.fallback.model} ({reason})"
        return out2, usage2

    def generate_text(self, system: str, prompt: str) -> tuple[str, Usage]:
        try:
            return self.primary.generate_text(system, prompt)
        except LLMConfigError:
            raise
        except LLMError as e:
            text, usage = self.fallback.generate_text(system, prompt)
            usage.note = f"{self.primary.model} → {self.fallback.model} ({self.primary.model} 실패: {e})"
            return text, usage
