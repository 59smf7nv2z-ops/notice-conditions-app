"""공급자 선택: .env의 LLM_PROVIDER=claude|gemini|mock, LLM_MODEL_EXTRACT, LLM_MODEL_WRITE.
claude일 때 LLM_MODEL_FALLBACK(예: claude-sonnet-5-5)이 있으면 실패·확신 낮음에 그 모델로 다시 한다.

모델명은 자주 바뀌므로 코드에 쓰지 않는다. 키나 모델명이 없으면 MockProvider(샘플 결과)로 돌아간다.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

from core.llm.mock import MockProvider

TASK_MODEL_ENV = {"extract": "LLM_MODEL_EXTRACT", "write": "LLM_MODEL_WRITE"}
PROVIDER_LABEL = {"claude": "Anthropic(Claude)", "gemini": "Google(Gemini)", "mock": "샘플(전송 없음)"}


@dataclass
class ProviderStatus:
    name: str  # claude | gemini | mock
    model: str
    is_mock: bool
    reason: str = ""  # mock으로 돌아간 이유

    @property
    def label(self) -> str:
        return PROVIDER_LABEL.get(self.name, self.name)


def status(task: str = "extract", provider: str | None = None) -> ProviderStatus:
    load_dotenv()
    name = (provider or os.environ.get("LLM_PROVIDER") or "mock").strip().lower()
    model = (os.environ.get(TASK_MODEL_ENV[task]) or "").strip()
    if name == "mock":
        return ProviderStatus("mock", "mock", True, "LLM_PROVIDER=mock")
    if name not in ("claude", "gemini"):
        return ProviderStatus("mock", "mock", True, f"알 수 없는 LLM_PROVIDER '{name}'")
    key_env = "ANTHROPIC_API_KEY" if name == "claude" else "GEMINI_API_KEY"
    if not (os.environ.get(key_env) or "").strip():
        return ProviderStatus("mock", "mock", True, f"{key_env}가 없어 샘플 결과를 씁니다")
    if not model:
        return ProviderStatus("mock", "mock", True, f"{TASK_MODEL_ENV[task]}(모델명)이 비어 샘플 결과를 씁니다")
    return ProviderStatus(name, model, False)


def get_provider(task: str = "extract", provider: str | None = None):
    st = status(task, provider)
    if st.is_mock:
        return MockProvider(reason=st.reason)
    if st.name == "claude":
        from core.llm.claude import ClaudeProvider, normalize_model

        key = os.environ["ANTHROPIC_API_KEY"].strip()
        primary = ClaudeProvider(st.model, api_key=key)
        fb = normalize_model(os.environ.get("LLM_MODEL_FALLBACK") or "")
        if fb and fb != primary.model:
            from core.llm.fallback import FallbackProvider

            return FallbackProvider(primary, ClaudeProvider(fb, api_key=key))
        return primary
    from core.llm.gemini import GeminiProvider

    return GeminiProvider(st.model, api_key=os.environ["GEMINI_API_KEY"].strip())


def available_providers() -> list[str]:
    """키와 모델명이 있는 실제 공급자(비교 스크립트용)."""
    return [p for p in ("claude", "gemini") if not status("extract", p).is_mock]
