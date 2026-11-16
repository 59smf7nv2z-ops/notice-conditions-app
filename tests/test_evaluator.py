"""판정 엔진 v2 테스트: 경계값, 조례 유형 6종, 주 조건표 선택, 상태 조합."""

import time
from datetime import date

import pandas as pd
import pytest

from core.conditions import BusinessType, NoticeConditions, NotJudgeableNoticeError
from core.evaluator import (
    CANDIDATE,
    NEEDS_CHECK,
    NOT_ELIGIBLE,
    ORDINANCE_ONLY,
    EvalOptions,
    evaluate,
    full_years,
    parse_approval,
)
from core.ordinances import OrdinanceConditions

EVAL = date(2026, 11, 15)


def bldg(**kw) -> dict:
    base = {
        "mgmBldrgstPk": "1",
        "platPlc": "가상 주소",
        "useAprDay": "19800101",
        "grndFlrCnt": 2,
        "ugrndFlrCnt": 0,
        "totArea": 150.0,
        "strctCdNm": "벽돌구조",
        "etcStrct": "",
        "mainPurpsCdNm": "단독주택",
        "etcPurps": "",
        "regstrGbCdNm": "일반",
        "mainAtchGbCdNm": "주건축물",
    }
    base.update(kw)
    return base


def notice(**kw) -> NoticeConditions:
    base = {"notice_id": "t", "business_type": BusinessType.APPLY_INSPECTION, "min_years": 30}
    base.update(kw)
    return NoticeConditions(**base)


def ordinance(rule: str, **kw) -> OrdinanceConditions:
    base = {"sido": "가상도", "sigungu": "가상군", "ordinance_name": "가상 조례", "scale_rule_type": rule}
    base.update(kw)
    return OrdinanceConditions(**base)


def run(rows: list[dict], n=None, o=None, eval_date=EVAL, options=None) -> pd.DataFrame:
    return evaluate(pd.DataFrame(rows), n, o, eval_date, options)


def one(row: dict, n=None, o=None, eval_date=EVAL, options=None) -> pd.Series:
    return run([row], n, o, eval_date, options).iloc[0]


# ---------------------------------------------------------------- 경계값


@pytest.mark.parametrize("bound, expected", [("LT", NOT_ELIGIBLE), ("LE", CANDIDATE)])
def test_area_200_boundary(bound, expected):
    r = one(bldg(totArea=200.0), notice(max_area=200, area_bound=bound))
    assert r.status == expected


@pytest.mark.parametrize(
    "floors, bound, expected",
    [(3, "LE", CANDIDATE), (3, "LT", NOT_ELIGIBLE), (4, "LE", NOT_ELIGIBLE), (2, "LT", CANDIDATE)],
)
def test_floor_3_boundary(floors, bound, expected):
    assert one(bldg(grndFlrCnt=floors), notice(max_floors=3, floors_bound=bound)).status == expected


@pytest.mark.parametrize(
    "eval_date, expected",
    [(date(2026, 11, 14), NOT_ELIGIBLE), (date(2026, 11, 15), CANDIDATE), (date(2026, 11, 16), CANDIDATE)],
)
def test_exactly_30_years_day(eval_date, expected):
    # 1996-11-15 사용승인 → 2026-11-15에 만 30년
    assert one(bldg(useAprDay="19961115"), notice(), eval_date=eval_date).status == expected


def test_full_years_is_korean_man_age():
    assert full_years(date(1996, 11, 15), date(2026, 11, 14)) == 29
    assert full_years(date(1996, 11, 15), date(2026, 11, 15)) == 30
    assert full_years(date(1996, 2, 29), date(2026, 2, 28)) == 29  # 윤일


@pytest.mark.parametrize(
    "apr, status, reason",
    [
        ("", NEEDS_CHECK, "APPROVAL_DATE_MISSING"),
        ("19950315", CANDIDATE, None),
        ("1995", CANDIDATE, None),  # 1995년 어느 날이든 30년 이상
        ("1996", NEEDS_CHECK, "APPROVAL_YEAR_ONLY_BOUNDARY"),  # 경계 연도만 UNKNOWN
        ("1997", NOT_ELIGIBLE, None),
        ("199611", NEEDS_CHECK, "APPROVAL_YEAR_ONLY_BOUNDARY"),
        ("19961100", NEEDS_CHECK, "APPROVAL_YEAR_ONLY_BOUNDARY"),  # 일 00
        ("abc", NEEDS_CHECK, "APPROVAL_DATE_MISSING"),
    ],
)
def test_approval_date_forms(apr, status, reason):
    r = one(bldg(useAprDay=apr), notice())
    assert r.status == status
    if reason:
        assert reason in r.check_reasons


def test_parse_approval_invalid_day_falls_back_to_month():
    a = parse_approval("19950231")
    assert (a.earliest, a.latest) == (date(1995, 2, 1), date(1995, 2, 28))


# ---------------------------------------------------------------- 공고 조건 세부


def test_built_before_year_inclusive_unknown():
    n = notice(years_basis="BUILT_BEFORE_YEAR", built_before_year=1994, built_before_inclusive=None, min_years=None)
    assert one(bldg(useAprDay="19930101"), n).status == CANDIDATE
    r = one(bldg(useAprDay="19940601"), n)
    assert r.status == NEEDS_CHECK and "BUILT_YEAR_BOUNDARY_UNCLEAR" in r.check_reasons
    assert one(bldg(useAprDay="19950101"), n).status == NOT_ELIGIBLE
    n2 = n.model_copy(update={"built_before_inclusive": True})
    assert one(bldg(useAprDay="19940601"), n2).status == CANDIDATE


def test_age_reference_apply_start():
    n = notice(age_reference="APPLY_START", apply_start=date(2026, 3, 1))
    # 1996-05-01 → 2026-03-01 기준 29년, 판정 기준일(11-15) 기준이면 30년
    assert one(bldg(useAprDay="19960501"), n).status == NOT_ELIGIBLE
    assert one(bldg(useAprDay="19960501"), notice()).status == CANDIDATE


def test_floors_basis_with_underground():
    n = notice(max_floors=3, floors_bound="LE", floors_basis="GROUND_AND_UNDERGROUND")
    assert one(bldg(grndFlrCnt=3, ugrndFlrCnt=1), n).status == NOT_ELIGIBLE
    assert one(bldg(grndFlrCnt=3, ugrndFlrCnt=1), notice(max_floors=3)).status == CANDIDATE


def test_missing_floor_or_area_is_unknown():
    r = one(bldg(grndFlrCnt=None, totArea=0), notice(max_floors=3, max_area=200))
    assert r.status == NEEDS_CHECK
    assert set(r.check_reasons) == {"FLOORS_MISSING", "AREA_MISSING"}


def test_structure_condition():
    n = notice(structure_filter=["조적조"])
    assert one(bldg(strctCdNm="벽돌구조"), n).status == CANDIDATE
    assert one(bldg(strctCdNm="철근콘크리트구조"), n).status == NOT_ELIGIBLE
    r = one(bldg(strctCdNm="철골철근콘크리트구조"), n)
    assert r.status == NEEDS_CHECK and r.check_reasons == ["STRUCTURE_UNMAPPED"]
    # 구조 조건이 없으면 미매핑이어도 UNKNOWN이 아니다
    assert one(bldg(strctCdNm="철골철근콘크리트구조"), notice()).status == CANDIDATE


def test_housing_scope_unclear():
    r = one(bldg(mainPurpsCdNm="공동주택", etcPurps="다세대주택"), notice(use_filter=["주택"]))
    assert r.status == NEEDS_CHECK and r.check_reasons == ["HOUSING_SCOPE_UNCLEAR"]


def test_collective_excluded():
    n = notice(collective_excluded=True)
    assert one(bldg(regstrGbCdNm="집합"), n).status == NOT_ELIGIBLE
    assert one(bldg(regstrGbCdNm="집합"), notice()).status == CANDIDATE
    # legacy '집합건물 제외' 설정
    assert one(bldg(regstrGbCdNm="집합"), notice(), options=EvalOptions(exclude_collective=True)).status == NOT_ELIGIBLE


def test_annex_building_default_excluded():
    r = one(bldg(mainAtchGbCdNm="부속건축물"), notice())
    assert r.status == NOT_ELIGIBLE and r.reasons == ["ANNEX_BUILDING"]
    assert one(bldg(mainAtchGbCdNm="부속건축물"), notice(), options=EvalOptions(include_annex=True)).status == CANDIDATE


def test_offmap_conditions_go_to_checklist_not_status():
    n = notice(offmap_conditions=["위원회 심사", "현장 위험도 평가"])
    r = one(bldg(), n)
    assert r.status == CANDIDATE
    assert r.field_checklist == ["위원회 심사", "현장 위험도 평가"]
    assert one(bldg(useAprDay="20100101"), n).field_checklist == []  # 비해당에는 붙이지 않음


def test_non_application_notice_raises():
    with pytest.raises(NotJudgeableNoticeError):
        run([bldg()], notice(business_type=BusinessType.EX_OFFICIO_INSPECTION))
    with pytest.raises(NotJudgeableNoticeError):
        run([bldg()], notice(business_type=BusinessType.REPAIR_SUPPORT))


# ---------------------------------------------------------------- 조례 유형 6종 (공고 없음 → 조례가 주 조건표)


def test_ordinance_numeric():
    o = ordinance("NUMERIC", max_floors=2, floors_bound="LE", max_area=500, area_bound="LT")
    assert one(bldg(grndFlrCnt=2, totArea=499.9), None, o).status == CANDIDATE
    assert one(bldg(grndFlrCnt=2, totArea=500), None, o).status == NOT_ELIGIBLE
    assert one(bldg(), None, o).primary_table == "조례"


def test_ordinance_discretion_only_age():
    o = ordinance("DISCRETION")
    r = one(bldg(grndFlrCnt=10, totArea=5000), None, o)
    assert r.status == CANDIDATE
    assert "조례에 규모 수치 없음" in r.notes


def test_ordinance_none_type():
    r = one(bldg(grndFlrCnt=10), None, ordinance("NONE"))
    assert r.status == CANDIDATE and "조례에 규모 수치 없음" in r.notes


def test_ordinance_structure_rule_ref_unknown_without_override():
    o = ordinance("STRUCTURE_RULE_REF", committee_required=True)
    r = one(bldg(), None, o)
    assert r.status == NEEDS_CHECK and r.check_reasons == ["ORD_SCALE_EXTERNAL_REF"]
    assert any("구조기준규칙" in c for c in r.field_checklist)
    o2 = o.model_copy(update={"manual_override": {"max_floors": 2, "floors_bound": "LE", "max_area": 500, "area_bound": "LT"}})
    assert one(bldg(), None, o2).status == CANDIDATE
    assert one(bldg(totArea=600), None, o2).status == NOT_ELIGIBLE


def test_ordinance_construction_act_ref_dangjin_style():
    # 당진: 3층 이상 AND 건설사업자 시공 이외 → 층수는 판정, 시공자 여부는 확인필요
    o = ordinance("CONSTRUCTION_ACT_REF", min_floors=3, min_floors_bound="GE")
    assert one(bldg(grndFlrCnt=2), None, o).status == NOT_ELIGIBLE
    r = one(bldg(grndFlrCnt=3), None, o)
    assert r.status == NEEDS_CHECK and r.check_reasons == ["ORD_SCALE_EXTERNAL_REF"]
    assert any("건설산업기본법 제41조" in c for c in r.field_checklist)


def test_ordinance_use_structure():
    o = ordinance("USE_STRUCTURE", structure_filter=["조적조"], private_only=True)
    r = one(bldg(), None, o)
    assert r.status == CANDIDATE
    assert "조례: 민간건축물 여부(공공건축물 제외)" in r.field_checklist
    assert one(bldg(strctCdNm="목구조"), None, o).status == NOT_ELIGIBLE
    o2 = ordinance("USE_STRUCTURE", use_filter=["단독주택(다가구주택 제외)", "지역아동센터"])
    assert one(bldg(etcPurps="다가구주택"), None, o2).status == NOT_ELIGIBLE
    assert one(bldg(mainPurpsCdNm="노유자시설", etcPurps="지역아동센터"), None, o2).status == CANDIDATE


def test_ordinance_years_set_yearly():
    o = ordinance("USE_STRUCTURE", min_years=None, structure_filter=["조적조"])
    r = one(bldg(), None, o)
    assert r.status == NEEDS_CHECK and r.check_reasons == ["ORD_YEARS_YEARLY"]
    assert one(bldg(useAprDay="20000101"), None, o).status == NOT_ELIGIBLE  # 법정 30년 미달


def test_no_notice_no_ordinance_legal_30_only():
    df = run([bldg(grndFlrCnt=20, totArea=9999), bldg(useAprDay="20000101")])
    assert list(df.status) == [CANDIDATE, NOT_ELIGIBLE]
    assert df.iloc[0].primary_table == "법정"
    assert any("법정 기준" in n for n in df.iloc[0].notes)


# ---------------------------------------------------------------- 공고 + 조례 조합


def test_ordinance_only_when_notice_fails_and_ordinance_numbers_pass():
    n = notice(min_years=40, max_floors=3, max_area=200, area_bound="LT")  # 광주 동구 조건 예
    o = ordinance("NUMERIC", max_floors=3, floors_bound="LE", max_area=1000, area_bound="LE")
    r = one(bldg(useAprDay="19900101", totArea=300), n, o)  # 36년, 300㎡
    assert r.status == ORDINANCE_ONLY
    assert r.reasons[0] == "NOTICE_FAIL_ORDINANCE_PASS" and "FAIL_AGE" in r.reasons and "FAIL_AREA" in r.reasons
    assert r.ordinance_detail and r.notice_detail


def test_no_ordinance_only_without_ordinance_numbers():
    n = notice(max_area=200, area_bound="LT")
    for o in (ordinance("DISCRETION"), ordinance("STRUCTURE_RULE_REF"), None):
        assert one(bldg(totArea=300), n, o).status == NOT_ELIGIBLE


def test_no_ordinance_only_when_ordinance_unknown():
    n = notice(max_area=200, area_bound="LT")
    o = ordinance("NUMERIC", max_area=1000, structure_filter=["조적조"])
    assert one(bldg(totArea=300, strctCdNm="철골철근콘크리트구조"), n, o).status == NOT_ELIGIBLE


def test_every_row_has_reason():
    rows = [bldg(), bldg(useAprDay=""), bldg(useAprDay="20100101"), bldg(mainAtchGbCdNm="부속")]
    df = run(rows, notice(max_area=200))
    assert all(df.reasons.map(len) > 0)
    assert all(df.reason_text.str.len() > 0)


def test_output_columns():
    df = run([bldg()], notice())
    for col in (
        "status", "reasons", "reason_text", "check_reasons", "field_checklist",
        "notice_detail", "ordinance_detail", "age_years", "structure_std", "use_std",
    ):
        assert col in df.columns
    assert df.iloc[0].age_years == 46
    assert df.iloc[0].structure_std == "조적조"


def test_performance_359_rows_under_1s():
    rows = [bldg(mgmBldrgstPk=str(i), useAprDay=f"{1960 + i % 60}0101", totArea=100 + i) for i in range(359)]
    n = notice(min_years=40, max_floors=3, max_area=200, area_bound="LT", use_filter=["주택"])
    o = ordinance("NUMERIC", max_floors=3, max_area=1000)
    t = time.perf_counter()
    run(rows, n, o)
    assert time.perf_counter() - t < 1.0
