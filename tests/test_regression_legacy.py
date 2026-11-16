"""legacy 판정과의 회귀 테스트 (청운동 359건, 광주 동구 조건 → 65/36/258).

필요 자료(scripts/legacy/README.md)를 받기 전까지는 건너뛴다.
자료가 들어오면: legacy 판정 코드를 core/evaluator_legacy.py로 그대로 옮기고,
광주 동구 조건을 NoticeConditions로 변환해 v2와 비교한다.
  legacy 후보 = v2 CANDIDATE, legacy 확인필요 = v2 NEEDS_CHECK,
  legacy 제외 = v2 NOT_ELIGIBLE + ORDINANCE_ONLY
legacy 확인필요에 대장 외 조건이 섞여 있었다면 억지로 맞추지 말고 차이 건수와 이유를 보고한다.
"""

from pathlib import Path

import pytest

FIXTURES = Path(__file__).resolve().parent / "fixtures"
NEEDED = [FIXTURES / "cheongun_title.json", FIXTURES / "sample30_truth.csv"]

if not all(p.exists() for p in NEEDED):
    pytest.skip(
        "legacy 회귀 자료 미수령: tests/fixtures/cheongun_title.json, sample30_truth.csv (scripts/legacy/README.md)",
        allow_module_level=True,
    )
