# Cursor 입력용 프롬프트 — 소규모 노후건축물 안전점검 지원 대상 선별 시스템

## 사용법
1. `00_project_rules.mdc`를 저장소의 `.cursor/rules/project.mdc`로 저장한다.
   모든 대화에 자동 적용되는 공통 규칙(원칙, 상태 정의, 디렉터리 구조)이다.
2. `env.example`을 `.env.example`로 저장하고, 복사본 `.env`에 실제 키를 넣는다.
3. 단계마다 Cursor Agent 새 대화를 열고 해당 파일 내용을 통째로 붙여 넣는다.
4. 단계가 끝나면 `pytest -q` 통과를 확인하고 커밋한 뒤 다음 단계로 간다.
   테스트가 깨진 채로 다음 단계로 넘어가지 않는다.

## 시작 전 준비물 (저장소에 넣어 둘 것)
| 위치 | 내용 |
|---|---|
| scripts/legacy/ | 기존 대장 조회·판정 스크립트, 공고 추출 스크립트, 정확도 계산 코드, Streamlit 프로토타입 |
| data/ordinances/ | 조례 CSV |
| data/notices/ | 공고 6건 추출 결과 + 사람 확정 정답 |
| tests/fixtures/ | 청운동 359건 조회 결과(있으면), 표본 30건 사람 판정 |
| data/ref/ | 법정동코드 전체자료(행정표준코드관리시스템에서 최신본 다운로드) |
| frontend_grok/ | grok 웹앱 소스(내려받을 수 있으면, 참고용) |

## 단계 순서
| 단계 | 파일 | 요구사항 | 필요한 키 |
|---|---|---|---|
| 1 | 01_setup_regression.md | 기반 정리, 회귀 테스트 | (기존) 건축물대장 |
| 2 | 02_conditions_evaluator.md | 조례·공고 조건표, 판정 엔진 v2 | 없음 |
| 3 | 03_building_api.md | 요구 2: 조회 즉시 인메모리 일괄 대조 | 건축물대장 |
| 4 | 04_region_batch_ui.md | 요구 1: 지역 일괄 대조·결과 추출, Streamlit 화면 | 건축물대장 |
| 5 | 05_map_drilldown.md | 요구 3: 지도 드릴다운 | 브이월드 |
| 6 | 06_llm_providers.md | Claude/Gemini 전환, 공고 업로드 추출 | Claude 또는 Gemini |
| 7 | 07_later_notice_search_ordinance_sync.md | 후순위: 공고 자동 탐색, 조례 동기화 | 네이버, 법제처 |
| 선택 | 08_optional_fastapi_grok.md | grok 화면을 계속 쓸 때 | — |

단계 1에서는 Cursor가 기존 코드를 읽고 보고한 뒤 멈춘다. 보고를 확인하고 "진행"이라고 입력한다.
