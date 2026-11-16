# [단계 2/7] 지역코드·조례 로더·조건표 스키마·판정 엔진 v2

## 목표
공고 조건표와 조례 조건표를 따로 평가해 4상태(CANDIDATE / NEEDS_CHECK / ORDINANCE_ONLY / NOT_ELIGIBLE)를
내는 판정 엔진을 만든다. legacy 판정과의 호환은 회귀 테스트로 보장한다.
상태 정의는 .cursor/rules/project.mdc를 따른다.

## 2-1 지역코드 (core/regions.py)
- data/ref/의 법정동코드 전체자료(탭 구분 txt, 컬럼: 법정동코드·법정동명·폐지여부, 인코딩 cp949 가능)를 로드. "존재"만 사용.
- 함수: list_sido(), list_sigungu(sido) -> [(sigunguCd, 이름)], list_bjdong(sigunguCd) -> [(bjdongCd, 표시이름)], name_of(code)
- 건축물대장 bjdongCd는 읍면동 3자리 + 리 2자리다.
  하위 리가 있는 읍·면은 목록에서 빼고 리 코드를 "○○면 ○○리"로 표시한다. 리가 없는 동은 그대로 쓴다.
- core는 streamlit을 import하지 않는다. 캐시는 functools.lru_cache.
- 테스트: "서울특별시 종로구 청운동" 코드 조회, 인천 제물포구·영종구·검단구가 목록에 있는지(없으면 데이터 파일이 오래된 것이므로 경고).

## 2-2 조례 로더 (core/ordinances.py)
- data/ordinances/의 CSV → OrdinanceConditions(pydantic). 컬럼 매핑은 단계 1에서 확인한 실제 컬럼명으로 dict를 정의한다.
- 표준 필드: sido, sigungu, sigungu_codes(list), ordinance_name, effective_date, scale_rule_type,
  min_years(기본 30), max_floors, floors_bound(LE|LT), max_area, area_bound(LE|LT),
  use_filter, structure_filter, exclusions(list), committee_required(bool), source_article, manual_override(dict|None)
- scale_rule_type 처리:
  - NUMERIC(수치 명시): 수치 그대로
  - DISCRETION(단체장 재량), NONE(점검대상 조문 없음): 규모 필터 없음. 조례 평가는 30년만, note "조례에 규모 수치 없음"
  - STRUCTURE_RULE_REF(구조기준규칙상 소규모건축물 참조), CONSTRUCTION_ACT_REF(건설산업기본법 시공 대상 이외):
    외부 기준을 참조하는 유형이다. 수치를 추측해서 넣지 않는다.
    manual_override에 담당자가 수치를 넣으면 그 값을 쓰고, 없으면 규모 조건을 UNKNOWN(사유 ORD_SCALE_EXTERNAL_REF)으로 둔다.
  - USE_STRUCTURE(용도·구조 기준): use_filter, structure_filter 적용
- 지역 매핑: 시도+시군구 이름 → sigunguCd 목록(1:N). 공백·약칭(서울시/서울특별시 등)을 정규화해 비교.
  - scripts/check_ordinance_mapping.py: 매칭 실패, 다중 매칭, 폐지 코드 매칭, 조례 없는 시군구를 표로 출력
  - 인천 제물포구·영종구·검단구, 광주 통합 관련 지역은 반드시 이 리포트에 나오게 하고 자동 추정하지 않는다
  - 수동 매핑은 data/ordinances/mapping_overrides.csv
- get_ordinance(sigunguCd) -> OrdinanceConditions | None

## 2-3 공고 조건 스키마 (core/conditions.py)
기존 조건 파일 형식을 기준으로 NoticeConditions(pydantic)를 정의한다. 기존 필드명은 유지(필요하면 alias)하고 아래를 추가한다.
- business_type: APPLY_INSPECTION | EX_OFFICIO_INSPECTION | REPAIR_SUPPORT | MULTI_HOUSING_SUBSIDY | HOUSING_REDEVELOPMENT | UNRELATED
  판정은 APPLY_INSPECTION만 한다.
- sigungu_codes: list[str]
- apply_start, apply_end: date | None — LLM은 날짜만 추출. 마감 여부는 메서드 is_expired(today)로 코드가 계산.
- years_basis: ELAPSED_YEARS(min_years) | BUILT_BEFORE_YEAR(built_before_year, inclusive: bool | None)
  "1994년 이전"처럼 해석이 갈리면 inclusive=None으로 두고 해당 연도 건물은 UNKNOWN 처리.
- age_reference: EVAL_DATE(기본) | APPLY_START | NOTICE_DATE — 경과연수를 어느 날짜 기준으로 셀지
- floors_basis: GROUND_ONLY(기본) | GROUND_AND_UNDERGROUND
- collective_excluded: bool | None, multi_housing_excluded: bool | None
- priority_rules: list[str] — 판정에 쓰지 않고 정렬·표시용
- offmap_conditions: list[str] — 대장 외 조건 → field_checklist
- source_type: OFFICIAL_NOTICE | LEAFLET | PRESS_RELEASE | NEWS
- reviewed: bool, evidence: dict[필드명, 원문 인용]
- contact: 접수처, 문의처, 신청방법, 제출서류
- 공고 6건의 기존 조건 파일을 새 스키마로 변환하는 scripts/migrate_notices.py. 변환 불가 필드는 리포트.

## 2-4 정규화 (core/normalize.py + data/ref/structure_map.csv, use_map.csv)
- structure_map.csv: 대장 표기(strctCdNm 또는 etcStrct 문자열) → 표준 구조(조적조, 목조, 철근콘크리트조, 철골조, 기타)
  - 확실한 값만 넣는다(벽돌구조, 블록구조, 석구조, 조적구조, 기타조적구조, 시멘트블럭조, 연와조, 목구조, 철근콘크리트구조, 일반철골구조, 경량철골구조 등).
  - 매칭 실패 → None. 공고·조례에 구조 조건이 있을 때만 UNKNOWN(STRUCTURE_UNMAPPED).
- use_map.csv: mainPurpsCdNm·etcPurps → 표준 용도(단독주택, 공동주택, 제1종근생, 제2종근생, 노유자시설 등) + is_mixed
  - "주택및근린생활시설" 같은 복합 표기는 is_mixed=True
  - 공고가 "주택"이라고만 하고 공동주택 포함 여부가 불명이면 공동주택 건물은 UNKNOWN(HOUSING_SCOPE_UNCLEAR)
- 실행마다 미매핑 구조·용도 값과 건수를 반환해 담당자가 CSV에 추가할 수 있게 한다.

## 2-5 판정 엔진 (core/evaluator.py)
- evaluate(df, notice, ordinance, eval_date, options) -> DataFrame
- 조건 단위 평가 함수 evaluate_table(row, table) -> {조건명: PASS | FAIL | UNKNOWN, 기준, 대장값}를 공고·조례에 각각 적용한다.
- 상태 조합:
  - 주 조건표 = notice (business_type이 APPLY_INSPECTION일 때), 아니면 ordinance, 둘 다 없으면 법정 30년만
  - 주 조건표 전부 PASS → CANDIDATE
  - FAIL 없음 + UNKNOWN 있음 → NEEDS_CHECK
  - FAIL 있음 → 공고가 주 조건표이고 조례 규모 수치가 있으며 조례 평가가 전부 PASS면 ORDINANCE_ONLY, 아니면 NOT_ELIGIBLE
- legacy 규칙 이식: 사용승인일 공란 → UNKNOWN, 연도만 있으면 경계 연도에서만 UNKNOWN, 집합건물 제외 설정.
- 부속건축물(mainAtchGbCdNm이 부속): 기본 NOT_ELIGIBLE(ANNEX_BUILDING), options로 포함 가능.
- 경과연수: 사용승인일 → 기준일까지 만 나이식. legacy 방식과 다르면 legacy를 따르고 차이를 보고.
- 출력 컬럼: 대장 핵심 컬럼 + status, reasons, reason_text, check_reasons, field_checklist,
  notice_detail, ordinance_detail, age_years, structure_std, use_std
- pandas로 구현하되 가독성 우선. 359건 기준 1초 이내.

## 2-6 테스트
- 회귀: 광주 동구 조건을 NoticeConditions로 변환해 v2 실행 → legacy와 비교
  - legacy 후보 = v2 CANDIDATE, legacy 확인필요 = v2 NEEDS_CHECK, legacy 제외 = v2 NOT_ELIGIBLE + ORDINANCE_ONLY
  - 단계 1에서 legacy 확인필요에 대장 외 조건이 섞여 있었다면 맞추려고 억지로 고치지 말고 차이 건수와 이유를 보고
- 경계값: 연면적 200.0(미만 → FAIL, 이하 → PASS), 층수 3, 경과연수 정확히 30년이 되는 날 전·후,
  사용승인일 ""·"1995"·"19950315"
- 조례 유형 6종 각 1케이스, 공고 없음 → 조례 기준, 조례도 없음 → 30년만 + note
- 비신청형 공고(EX_OFFICIO_INSPECTION 등)를 넣으면 판정하지 않고 명확한 예외

## 완료 기준
`pytest -q` 통과, check_ordinance_mapping.py와 migrate_notices.py 실행 결과(실패 목록 포함)를 보여줄 것.
