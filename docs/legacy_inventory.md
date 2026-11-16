# 기존 코드·자료 조사 보고 (단계 1)

작성: 2026-11-15. 받은 팀원 레포 zip(`notice-conditions-cursor-notice-extractor-0107`)을 읽고 정리했다.
원본은 `frontend_grok/`으로 옮겼고 내용은 수정하지 않았다(빌드 캐시 `tsconfig.tsbuildinfo`만 삭제).

## 0. 요약: 계획의 전제와 다른 점

받은 zip은 **Next.js 웹앱(grok 화면)뿐**이다. 파이썬 파일·CSV·테스트는 0개였다.

| 계획이 전제한 것 | 상태 |
|---|---|
| 대장 표제부 일괄 조회 스크립트 | 없음 (웹앱은 모의 대장만) |
| 검증된 판정 코드 (청운동 359건 → 65/36/258) | 없음 (TS 단건 판정 함수만) |
| 조례 CSV 220건과 규모규정 분류 | 원본 225행은 별도로 받음. **분류 컬럼 없음 → 새로 분류** |
| 공고 6건 추출 결과 + 정답 | 없음 (샘플 JSON 1건) |
| 정확도 계산 코드, Streamlit 프로토타입 | 없음 |
| 추출 프롬프트·항목 정의, HWP/HWPX 읽기 | 있음 (TS) |

그래서 legacy 회귀 테스트(65/36/258, 표본 30건)와 정확도 스모크 테스트는 자료를 받을 때까지 보류한다.
필요한 자료 목록: [scripts/legacy/README.md](../scripts/legacy/README.md)

## 1. 파일별 역할, 진입점, 외부 의존성 (frontend_grok/)

- 스택: Next.js 15, React 19, TypeScript, Tailwind 4, `@anthropic-ai/sdk`, jszip, cfb, iconv-lite, leaflet, pg/pglite
- 진입점: `app/page.tsx` → `DashboardProvider` + `DashboardShell`(4탭). `npm run dev` (127.0.0.1:3000)
- API 라우트
  - `app/api/extract/route.ts`: 업로드 → 추출. 로그인·출처·CSRF·호출 제한 검사
  - `app/api/status/route.ts`: 키 유무(mock), 로그인, CSRF 토큰
  - `app/api/geocode/route.ts`: **Nominatim** 주소 검색 (새 시스템은 브이월드)
- lib/
  - `schema.ts`: 시스템 프롬프트, 도구 스키마, 용량 제한, 모델명
  - `extract.ts`: Claude 호출, 모양 오류 시 1회 재시도, 키 없으면 샘플
  - `readers.ts`: HWPX·HWP·DOCX·HTML·txt → 텍스트, PDF·이미지는 원본
  - `compare.ts`: 판정 함수 `judgeBuilding`
  - `registry.ts`: 모의 대장, 경과연수 계산
  - `guide.ts`: 안내문 3말투(코드가 조립, LLM 미사용)
  - `map-model.ts`, `map-search.ts`, `korea-sido.ts`: 시도 단위 지도, 좌표는 하드코딩 + 해시 오프셋(가짜)
  - `http.ts`, `csrf.ts`, `rate-limit.ts`, `db.ts`, `cursor/identity.ts`: Cursor Apps 배포용 보안·로그인
- 외부 의존: Anthropic API, Nominatim, OSM/CARTO 타일, Cursor 로그인 서버, Postgres(호출 제한)
- 미사용 컴포넌트: `NoticeExtractTab`, `BuildingCompareTab`, `GuideReportTab`, `buildGuide()`

## 2. 판정 함수 (`lib/compare.ts` `judgeBuilding`)

- 입력: 건물 1건(`ageYears`, `floors`, `floorArea`, `use`, `structure`, `address`, 모두 문자열). 일괄 판정 없음
- 출력: `{ overall, checks[] }`, 행은 `{item, condition, building, verdict, note}`
- 상태 3개: 해당 / 비해당 / 확인필요. 비해당 1개라도 → 비해당, 아니면 확인필요 1개라도 → 확인필요
- 사유: 항목별 고정 한국어 문장. 사유 코드 없음
- "확인필요"에 들어가는 것: **데이터 불확실만**
  - 건물 값 미입력, "3층 이하" 문구 해석 실패
  - 공고에 경과연수·층수·연면적 조건 자체가 없을 때 (새 설계의 "조건 없으면 필터 없음"과 다름)
- 대장 외 조건(위원회 심사 등)은 상태에 섞이지 않고, LLM이 `확인필요` 목록으로 따로 뽑아 체크리스트로만 표시
- v2에 옮기면 안 되는 동작
  - 이하/미만 표기 없는 숫자를 "이하"로 간주
  - 용도·구조 부분 문자열 일치("주택"이 "공동주택"에 걸림)
  - 제외대상은 용도·주소 문자열과의 겹침만 봄
  - 지하층·집합건물·부속건축물 미평가

## 3. 판정 기준일

- 고정 기준일 없음. `registry.ts` `yearsSince(iso, now = new Date())`가 브라우저 현재 시각으로 만 나이 계산
- 판정 함수는 계산된 `ageYears`를 `>=`로 비교만 함. 사용자가 손으로 덮어쓸 수 있음
- 사용승인일 "1995"는 1995-01-01로 해석(경계 연도 UNKNOWN 없음), "19950315"(대장 형식)는 해석 실패
- 접수 마감 판정 없음(접수기간은 문자열)

## 4. 조건 파일 스키마

디스크 저장 없음. 브라우저 `sessionStorage`에 `Extracted`(`lib/types.ts`) 형태로만 둔다.
- 바깥: 공고, 파일명, 모델, 결과, skipped, readText, mock, warnings
- `결과` 18항목, 각 `{value, evidence}`: 지자체, 사업명, 연도, 시기, 사업유형, 경과연수, 층수, 연면적, 용도조건, 구조조건, 제외대상, 선정방식, 우선순위기준, 규모, 접수기간, 신청자격방법, 지원내용, 확인필요

```json
"경과연수": { "value": 30, "evidence": "사용승인 후 30년 경과" },
"층수":     { "value": "3층 이하", "evidence": "3층 이하" },
"연면적":   { "value": "1000㎡ 이하", "evidence": "연면적 1000㎡ 이하" },
"접수기간": { "value": "2026. 7. 1. ~ 2026. 7. 31.", "evidence": "..." }
```

새 스키마와의 차이: 층수·연면적이 문자열, 접수기간 문자열 하나, 사업유형 3종(새 설계 6종),
`sigungu_codes`·접수처·문의처·제출서류·`reviewed`·`source_type` 없음.

## 5. 조례 CSV

원본: `data/ordinances/ordinances_raw.csv` (UTF-8 BOM, 225행, 빈칸 없음)

- 컬럼 4개: 지자체, 조례명, 시행일(YYYYMMDD, 2020-10-30 ~ 2026-10-30), 조문
- **규모규정 유형 컬럼 없음** → 새로 분류하기로 결정. `scripts/classify_ordinances.py` → `data/ordinances/ordinance_conditions_draft.csv`
- 샘플 3행

| 지자체 | 조례명 | 시행일 | 조문 핵심 |
|---|---|---|---|
| 경기도 가평군 | 가평군 건축물관리 조례 | 20231226 | 구조기준규칙 제3조제2항의 소규모 건축물 중 구조전문위원회 자문 |
| 강원특별자치도 강릉시 | 강릉시 건축물관리 조례 | 20231227 | 2층 이하로서 연면적 5백제곱미터 미만, 구조전문위원회 자문 |
| 전남광주통합특별시 강진군 | 강진군 건축물관리 조례 | 20231106 | 2층 이하, 5백 제곱미터 미만, 건축위원회 심의, 정비구역 등 제외 |

- 분류 초안 결과(점검대상 216곳): NUMERIC 147, DISCRETION 40, STRUCTURE_RULE_REF 12, CONSTRUCTION_ACT_REF 11, USE_STRUCTURE 6. 검토필요 19곳
- 지원조문 7행(부산·울산 광역, 포항·거창·김해·동래·사천 지원 조항), 개편 전 조례 2행(옛 인천 동구·중구)은 판정에서 제외
- 조문 앞 `000600Y`(조문번호코드)와 제목이 본문에 붙어 있음. "5백", "1천500" 같은 한글 숫자 섞임
- 확정된 검토: 당진시 "3층 이상 AND 건설사업자가 시공한 건축물 이외"는 의도된 조건(오기 아님)
- 컬럼 설명: [data/ordinances/README.md](../data/ordinances/README.md)

### 법정동코드 (`data/ref/bjdong_codes_20260929.csv`)
- 계획서의 "탭 구분 txt"와 달리 **쉼표 구분 CSV, cp949**. 53,387행(존재 20,560)
- 인천 개편 반영: 제물포구 28125, 영종구 28155, 서해구 28275, 검단구 28290 존재 / 중구·동구·서구 폐지
  (규칙 문서의 "서구 → 서구·검단구"를 "서해구·검단구"로 고침)
- 광주·전남 통합 반영: 광주광역시(29)·전라남도(46) 전부 폐지 → 전남광주통합특별시(12). 광주 동구 = 1221000000
- 확인 필요(단계 3): 건축HUB 대장 API가 광주·전남에 새 코드(12)와 옛 코드(29/46) 중 무엇을 받는지

## 6. 공고 추출 프롬프트와 항목 정의

- 시스템 프롬프트: `frontend_grok/lib/schema.ts` `SYSTEM_PROMPT` (규칙 9개)
- 항목 정의: 같은 파일 `TOOL` (선정방식 분류 = 규칙 8, 용도 제한 vs 우선순위 = 규칙 9)
- 호출부: `frontend_grok/lib/extract.ts` (도구 호출, 모양 오류 시 1회 재시도)
- 오늘 날짜를 프롬프트에 넣지 않음(새 원칙과 일치). 별도 분류 단계 없이 사업유형을 한 항목으로 받음
- 단계 6 주의: 화면이 파일 하나당 요청 하나를 보냄 → 리플릿 앞뒤 면이 서로 다른 공고로 추출됨.
  HWPX 표를 줄 단위 텍스트로 풀어 버림(마크다운 표 아님)

## 7. 하드코딩된 키, 절대경로, 날짜

- API 키 0건(`ANTHROPIC_API_KEY`는 환경변수). 절대경로 0건
- 주의할 하드코딩
  - 모델명 `claude-sonnet-5-5` (`lib/schema.ts:1`) → 새 시스템은 .env
  - 배포 호스트 `notice-conditions.apps.grok.bot` (`lib/http.ts:60`)
  - CSRF 서명 비밀값: `CURSOR_APP_ID` 없으면 Anthropic 키를 재사용, 그것도 없으면 고정 문자열 (`lib/csrf.ts:7`)
  - Nominatim URL·User-Agent (`app/api/geocode/route.ts:32`)
- 날짜: 고정 기준일 없음. 샘플에만 2026. 7. 1.~7. 31., 1990-03-15, 2020-04-02

## 8. 단계 1 진행 결과

| 항목 | 결과 |
|---|---|
| 디렉터리 구조 | project.mdc 구조로 생성. 웹앱은 `frontend_grok/` |
| core/evaluator_legacy.py | **보류**: 옮길 legacy 파이썬 판정 코드가 없음 |
| 회귀 테스트 65/36/258, 표본 30 | **보류**: 청운동 응답·정답 없음 |
| 정확도 스모크 테스트 | **보류**: 정확도 코드·정답셋 없음 |
| 대신 넣은 테스트 | 법정동코드 형식·개편 반영, 조례 분류 고정값(이하/미만, 당진, OR 정의 등) |
| requirements.txt, .env.example, .gitignore, README | 작성. `pytest -q` 31 passed |
| 키 하드코딩 | `git grep` 키 패턴 0건 |
| 기존 Streamlit 프로토타입 실행 | 해당 없음(받지 못함). grok 웹앱 실행법을 README에 기재 |
