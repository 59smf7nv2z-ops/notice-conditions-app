# scripts/legacy — 기존 검증 코드 원본 (아직 받지 못함)

계획(docs/cursor_prompts/01_setup_regression.md)은 이 폴더에 팀의 검증된 파이썬 코드가 있다고 전제한다.
2026-11-15 현재 받은 zip에는 없다. 받으면 **수정하지 말고 원본 그대로** 여기에 넣는다.

| 필요한 자료 | 쓰이는 곳 |
|---|---|
| 건축물대장 표제부 일괄 조회 스크립트 | 단계 3 core/building_api.py 이식 |
| 규칙 판정 코드 (청운동 359건 → 후보 65 / 확인필요 36 / 제외 258) | core/evaluator_legacy.py, 회귀 테스트 |
| 공고 조건 추출 스크립트(LLM)와 프롬프트 | 단계 6 core/llm/ |
| 정확도 계산 코드 | 단계 6 공급자 비교 |
| Streamlit 프로토타입 | 화면 참고 |

함께 필요한 데이터
- data/notices/: 공고 6건 추출 결과 + 사람이 확정한 정답
- tests/fixtures/cheongun_title.json: 청운동 표제부 원본 응답(359건)
- tests/fixtures/sample30_truth.csv: 표본 30건 대장PK와 사람 판정
- 광주 동구 공고 조건 파일(40년·3층 이하·200㎡ 미만)과 기존 결과를 만든 판정 기준일

이 자료가 들어오기 전까지 legacy 회귀 테스트(65/36/258)는 만들 수 없다.
