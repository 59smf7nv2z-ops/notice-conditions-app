# data/ordinances — 지자체 건축물관리 조례

| 파일 | 내용 |
|---|---|
| ordinances_raw.csv | 수집 원본(UTF-8 BOM). 컬럼: 지자체, 조례명, 시행일(YYYYMMDD), 조문(조문번호코드+제목+본문). 225행 |
| ordinance_conditions_draft.csv | `scripts/classify_ordinances.py`가 만든 **분류 초안**. 사람 검토 전 |

## 초안 다시 만들기
```bash
python scripts/classify_ordinances.py
```
사람이 원문을 확인해 확정한 값은 스크립트의 `MANUAL`에 넣는다(`confirmed: True`).
초안 CSV를 직접 고치면 다시 생성할 때 덮어써진다. 검토본은 다른 이름으로 저장한다.

## 초안 컬럼
- row_role: 점검대상 / 지원조문(점검대상 아님) / 개편전조례(대체됨). 로더는 점검대상만 쓴다.
- scale_rule_type: NUMERIC, DISCRETION, STRUCTURE_RULE_REF, CONSTRUCTION_ACT_REF, USE_STRUCTURE
- min_years: 기본 30. 비어 있으면 조례가 연수를 따로 정함(예: 노원구 '매년 정한다')
- max_floors + floors_bound(LE 이하 / LT 미만), min_floors + min_floors_bound(GE 이상)
- max_area + area_bound(LE / LT), 단위 ㎡
- use_filter, structure_filter(조적조), private_only(민간건축물 한정)
- exclusions(원문 항목, `|` 구분), excl_collective(집합건물 제외), excl_multi_housing(ALL=주택법 공동주택 전체 / MANDATORY_MGMT=의무관리대상만)
- committee_required, approver: 대장 외 조건 → 상태는 바꾸지 않고 현장확인 체크리스트로
- evidence_definition, evidence_exclusion: 원문 근거
- note, review_needed, review_reason

## 확정된 검토 결과
- 충청남도 당진시: '3층 이상(>=3) AND 건설사업자가 시공한 건축물 이외'. 오기 아님(2026-11-15).
  시공자 조건은 대장으로 확정할 수 없으므로 층수 등을 통과하면 확인필요.

## 사람이 채우는 파일
| 파일 | 컬럼 | 용도 |
|---|---|---|
| mapping_overrides.csv | 지자체, sigungu_codes(`;` 구분), note | 이름으로 자동 연결되지 않는 지역을 사람이 확인해 연결 |
| scale_overrides.csv | 지자체, max_floors, floors_bound, max_area, area_bound, entered_by, note | 구조기준규칙·건설산업기본법 참조형 조례에 담당자가 확인한 수치 |
| ordinance_conditions.csv | 초안과 같음 | 검토를 마친 분류본. 있으면 로더가 초안 대신 이것을 쓴다 |

매핑 점검: `python scripts/check_ordinance_mapping.py`
(2026-11-15 기준: 조례 216건 모두 연결, 실패·충돌 0, 조례 없는 시군구 15곳)
