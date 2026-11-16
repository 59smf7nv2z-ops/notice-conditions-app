# 소규모 노후건축물 안전점검 지원 대상 선별 시스템

구청 건축안전센터 실무자가 지자체 공고문·조례의 지원 조건을 건축물대장과 대조해
안전점검 지원 **자격 후보** 건물을 찾고, 소유자 안내문 초안을 만드는 도구입니다.
결과는 "선정 대상"이 아니라 "자격 후보"이며, 최종 선정은 실무자·위원회가 합니다.

> **개발 지식 없이 써 보려면** [처음_사용하는_분께.txt](처음_사용하는_분께.txt)를 보세요.
> `시작하기(Mac).command` / `시작하기(Windows).bat` 더블클릭으로 설치·실행됩니다.

- 공통 규칙: [.cursor/rules/project.mdc](.cursor/rules/project.mdc)
- 단계별 작업 계획: [docs/cursor_prompts/](docs/cursor_prompts/)
- 기존 코드 조사 보고: [docs/legacy_inventory.md](docs/legacy_inventory.md)

## 현재 상태 (단계 7까지)

| 영역 | 상태 |
|---|---|
| `core/notice_hunter.py` | 공고 찾기: 검수된 공고 → 네이버 검색 후보 → 고른 링크만 본문 추출(미검수). robots.txt 존중, 첨부는 링크만 |
| `core/ordinance_sync.py`, `scripts/sync_ordinances.py` | 법제처 자치법규 변경 감지 → 제안·diff 리포트 → 사람이 승인하면 반영(운영자 PC 전용) |
| `core/llm/` | LLM 공급자 추상화(Claude·Gemini·mock), HWP·HWPX 전처리, 분류·추출, 사용량 로그(토큰·해시만) |
| `app/` | Streamlit 4탭(공고 보기, 지역 일괄 대조, 안내문·리포트, 지도 드릴다운) |
| `core/geocode.py`, `core/boundaries.py` | 브이월드 지오코더 2.0(필지당 1회, 지번→도로명), 2D 데이터 행정경계. 세션 캐시만 |
| `core/pipeline.py` | 여러 법정동 조회 → 메모리에서 판정. 조회한 동은 재조회 없이 재판정 |
| `core/export.py`, `core/letters.py` | Excel·CSV, 안내문(내장 틀 3종 + 검증, docx). 모두 메모리에서 생성 |
| `core/building_api.py` | 건축물대장 표제부(getBrTitleInfo) 법정동 단위 일괄 조회. 메모리에서만 처리, 저장 없음 |
| `core/regions.py` | 법정동코드: 시도·시군구(일반구는 구 단위)·법정동(리 포함) 목록, 조례 지역 매핑 |
| `core/conditions.py` | 공고 조건표 스키마 `NoticeConditions`, 접수 마감 판정 |
| `core/ordinances.py` | 조례 조건표 `OrdinanceConditions` 로더, 시군구코드 매핑 |
| `core/normalize.py` | 대장 구조·용도 정규화(`data/ref/structure_map.csv`, `use_map.csv`) |
| `core/evaluator.py` | 판정 엔진 v2 (CANDIDATE / NEEDS_CHECK / ORDINANCE_ONLY / NOT_ELIGIBLE) |
| `frontend_grok/` | 팀원 grok 웹앱(Next.js) 원본. 화면 참고용 |
| legacy 파이썬 코드·정답셋 | **미수령** → [scripts/legacy/README.md](scripts/legacy/README.md). legacy 회귀 테스트는 건너뜀 |

## 앱 실행

```bash
.venv/bin/python -m streamlit run app/main.py
```

http://localhost:8501 에서 열립니다.
- ② 지역 일괄 대조: 시·도 → 시·군·구 → 법정동(여러 개) 선택 → ‘조회·판정’
- 다른 지역 공고를 시험으로 적용하려면 사이드바 ‘다른 지역 공고 적용(시험용)’
- ④ 지도: 법정동 경계(조회한 동은 1차 후보 수로 채색) → ‘지도 좌표 가져오기’ → 핀·표에서 건물 선택 → 오른쪽 상세.
  미조회 동을 누르면 ‘이 동 조회·판정’으로 바로 조회합니다.
- 조회 결과·좌표는 브라우저 세션에만 있습니다. 새로고침하면 사라지는 것이 정상입니다
  (브이월드 지오코더 응답은 저장 금지).
- 배경지도는 OSM입니다. 브이월드 배경지도 타일은 인증키가 브라우저에 노출되어 쓰지 않습니다.
- 브이월드 인증키 발급 시 서비스 URL에 `localhost:8501`과 배포 도메인을 등록하세요.

- ① 공고문 분석: HWP·HWPX·PDF·PNG·JPG 업로드(여러 개 = 한 공고) → 사업유형 분류 → 조건 추출 → 원문 근거와 대조해 고친 뒤
  ‘검수 완료로 저장’ → `data/notices/`에 저장되고 탭2 공고 목록에 바로 나타납니다.
- LLM 사용량은 `data/logs/llm_usage.csv`(git 제외)에 시각·공급자·모델·작업·토큰·문서 해시만 남습니다.

## 운영 스크립트

```bash
.venv/bin/python scripts/sync_ordinances.py check
```
법제처 Open API로 조례 개정 여부 확인 → `data/ordinances/sync/<날짜>/proposal.csv`, `diff.md`. 원본은 바꾸지 않습니다.
(2026-11-15 실행: 목록 861건 중 우리 조례 220건 대조, 개정 2건 — 충남 예산군, 전남광주 해남군. 둘 다 분류 결과 변화 없음)
법제처 API는 **신청 때 등록한 IP의 PC에서만** 동작합니다(`LAW_API_OC` 필요). 검토 후 반영:

```bash
.venv/bin/python scripts/sync_ordinances.py apply data/ordinances/sync/YYYYMMDD/proposal.csv --yes
```

```bash
.venv/bin/python scripts/compare_providers.py
```
정답셋(`data/eval/<공고ID>/` 원본 파일 + `truth.json`)으로 키가 있는 공급자를 모두 돌려 일치율·분류 정확도·토큰을 표로 출력합니다(선택은 사람이).

```bash
.venv/bin/python scripts/smoke_building_api.py
```
청운동 표제부 실조회(건수·호출 수·소요시간) → 판정 엔진 v2 연결까지 확인. 주소는 출력하지 않습니다. `BUILDING_API_KEY` 필요.

```bash
.venv/bin/python scripts/check_ordinance_mapping.py
```
조례 ↔ 시군구코드 매핑 점검(실패·충돌·1:N·개편 지역·조례 없는 시군구).

```bash
.venv/bin/python scripts/migrate_notices.py --dry-run
```
기존 공고 추출 결과(`data/notices/legacy/*.json`) → `NoticeConditions` 변환 리포트.

## 설치

Python 3.11 이상.

```bash
python3 -m venv .venv
```

```bash
.venv/bin/python -m pip install -r requirements.txt
```

## .env 설정

```bash
cp .env.example .env
```

`.env`에 실제 키를 넣습니다. `.env`는 git에 올라가지 않습니다. 코드·테스트·로그에 키를 쓰지 않습니다.

| 키 | 필요한 단계 | 발급처 |
|---|---|---|
| BUILDING_API_KEY | 3 이후 | 공공데이터포털 "국토교통부_건축HUB_건축물대장정보 서비스" (Decoding 키) |
| VWORLD_GEOCODER_KEY | 5 | 브이월드 지오코더 API 2.0 키. 발급 시 서비스 URL에 `localhost:8501`과 배포 도메인 등록 |
| VWORLD_DATA_KEY | 5 | 브이월드 2D 데이터 API 키(행정경계). 지오코더 키와 따로 발급 |
| LLM_PROVIDER, LLM_MODEL_EXTRACT, LLM_MODEL_WRITE | 6 | `claude`면 ANTHROPIC_API_KEY, `gemini`면 GEMINI_API_KEY. 키나 모델명이 없으면 `mock`(샘플 결과, 외부 전송 없음) |

## 서버 배포 (Streamlit Community Cloud)

1. share.streamlit.io 에 GitHub 계정으로 로그인. **배포하는 계정은 리포지토리 admin 권한이 있어야 합니다**(초대받은 협업자는 보통 없음 → 소유자가 배포하거나 admin 권한을 줌).
2. Create app → 리포지토리·브랜치 선택, Main file path `app/main.py`.
3. Advanced settings → Python 3.12 또는 3.13, **Secrets** 칸에 `.env`와 같은 이름으로 붙여 넣기:
   ```toml
   BUILDING_API_KEY = "..."
   VWORLD_GEOCODER_KEY = "..."
   VWORLD_DATA_KEY = "..."
   LLM_PROVIDER = "gemini"
   LLM_MODEL_EXTRACT = "gemini-3.8-flash"
   LLM_MODEL_WRITE = "gemini-3.8-flash"
   GEMINI_API_KEY = "..."
   ```
   앱이 시작할 때 Secrets를 환경변수로 옮깁니다(`app/state.py` `load_secrets_into_env`). `LAW_API_OC`는 IP 등록 PC 전용이라 넣지 않습니다.
4. 비공개 리포지토리에서 배포하면 앱도 비공개입니다. Share → 팀원 이메일로 초대(계정당 비공개 앱 1개).
5. 브이월드 키 설정의 서비스 URL에 배포 주소(`*.streamlit.app`)를 추가합니다.
6. 서버 디스크는 재시작 때 지워집니다. ①에서 ‘검수 완료로 저장’한 공고는 서버에서 사라지므로, 확정 공고는 `data/notices/`에 커밋해 두세요.

## 테스트

```bash
.venv/bin/python -m pytest -q
```

외부 API를 실제로 부르는 테스트는 `@pytest.mark.live`로 표시하며 기본으로 건너뜁니다.

```bash
.venv/bin/python -m pytest -q -m live
```

## 조례 분류 초안 다시 만들기

```bash
.venv/bin/python scripts/classify_ordinances.py
```

자세한 컬럼 설명은 [data/ordinances/README.md](data/ordinances/README.md).

## 기존 grok 웹앱 실행 (참고용)

Streamlit 프로토타입은 받지 못했습니다. 받은 것은 Next.js 웹앱이며 Node.js가 필요합니다.

```bash
cd frontend_grok && npm install && npm run dev
```

http://127.0.0.1:3000 에서 열립니다. `ANTHROPIC_API_KEY`가 없으면 샘플 결과로 동작합니다.
이 앱의 대장 조회는 모의 데이터이고, 주소 검색은 Nominatim을 씁니다(새 시스템에서는 브이월드로 교체).
