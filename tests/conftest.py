import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# core/ 패키지와 scripts/ 모듈을 테스트에서 import 할 수 있게 한다
for p in (ROOT, ROOT / "scripts"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))


import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _isolate_llm_usage_log(tmp_path, monkeypatch):
    """테스트가 실제 data/logs/llm_usage.csv에 쓰지 않도록 기본 경로를 임시 폴더로 돌린다."""
    monkeypatch.setenv("LLM_USAGE_LOG", str(tmp_path / "llm_usage_default.csv"))
