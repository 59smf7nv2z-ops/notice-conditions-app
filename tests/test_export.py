import io
from collections import Counter
from datetime import date

import pandas as pd
from openpyxl import load_workbook

from core.conditions import BusinessType, NoticeConditions
from core.evaluator import evaluate
from core.export import COLUMNS, ExportSummary, export_filename, result_table, to_csv_bytes, to_excel_bytes
from core.ordinances import OrdinanceConditions

EVAL = date(2026, 11, 15)


def result_df(test_mode: bool = False) -> pd.DataFrame:
    rows = [
        {"mgmBldrgstPk": "1000000000000000000001", "platPlc": "가상동 1", "newPlatPlc": "가상로 1", "useAprDay": "19800101",
         "grndFlrCnt": 2, "ugrndFlrCnt": 0, "totArea": 150.0, "strctCdNm": "벽돌구조", "mainPurpsCdNm": "단독주택",
         "etcPurps": "주택", "regstrGbCdNm": "일반", "mainAtchGbCdNm": "주건축물"},
        {"mgmBldrgstPk": "2", "platPlc": "가상동 2", "useAprDay": "", "grndFlrCnt": 2, "totArea": 150.0,
         "strctCdNm": "벽돌구조", "mainPurpsCdNm": "단독주택", "regstrGbCdNm": "일반", "mainAtchGbCdNm": "주건축물"},
        {"mgmBldrgstPk": "3", "platPlc": "가상동 3", "useAprDay": "19800101", "grndFlrCnt": 2, "totArea": 500.0,
         "strctCdNm": "벽돌구조", "mainPurpsCdNm": "단독주택", "regstrGbCdNm": "일반", "mainAtchGbCdNm": "주건축물"},
        {"mgmBldrgstPk": "4", "platPlc": "가상동 4", "useAprDay": "20200101", "grndFlrCnt": 2, "totArea": 100.0,
         "strctCdNm": "벽돌구조", "mainPurpsCdNm": "단독주택", "regstrGbCdNm": "일반", "mainAtchGbCdNm": "주건축물"},
    ]
    n = NoticeConditions(notice_id="t", program_name="시험 공고", business_type=BusinessType.APPLY_INSPECTION,
                         min_years=30, max_area=200, area_bound="LT", offmap_conditions=["위원회 심사"],
                         evidence={"max_area": "연면적 200㎡ 미만"})
    o = OrdinanceConditions(sido="가상도", sigungu="가상군", ordinance_name="가상 조례", scale_rule_type="NUMERIC",
                            max_area=1000, area_bound="LE")
    df = evaluate(pd.DataFrame(rows), n, o, EVAL)
    if test_mode:
        df["test_mode"] = True
    return df, n, o


def test_result_table_columns_and_values():
    df, _, _ = result_df()
    t = result_table(df)
    assert list(t.columns) == [c for c, _ in COLUMNS]
    first = t.iloc[0]
    assert first["상태"] == "1차 후보"
    assert first["현장확인 항목"] == "위원회 심사"
    assert first["주구조(원문/표준)"] == "벽돌구조 / 조적조"
    assert first["주용도(원문/기타용도)"] == "단독주택 / 주택"
    assert first["대장PK"] == "1000000000000000000001"
    assert t.iloc[1]["확인필요 사유"] == "사용승인일이 대장에 없음"


def test_csv_is_utf8_sig():
    df, _, _ = result_df()
    b = to_csv_bytes(df)
    assert b.startswith(b"\xef\xbb\xbf")
    assert "지번주소" in b.decode("utf-8-sig").splitlines()[0]


def test_excel_sheets_and_summary():
    df, n, o = result_df()
    s = ExportSummary(region="가상도 가상군 가상동", eval_date=EVAL, notice=n, ordinance=o,
                      unmapped_structures=Counter({"철골철근콘크리트구조": 2}))
    wb = load_workbook(io.BytesIO(to_excel_bytes(df, s)))
    assert wb.sheetnames == ["요약", "조건표", "1차후보", "확인필요", "조례만충족", "비해당", "미매핑값"]
    summary = {r[0]: r[1] for r in wb["요약"].iter_rows(min_row=2, values_only=True)}
    assert summary["공고 검수 여부"] == "미검수"
    assert summary["판정 기준일"] == "2026-11-15"
    assert (summary["1차 후보"], summary["확인필요"], summary["조례만 충족"], summary["비해당"]) == (1, 1, 1, 1)
    cond = list(wb["조건표"].iter_rows(values_only=True))
    assert cond[0] == ("조건", "공고 기준", "조례 기준", "공고 원문 근거")
    area = [r for r in cond if r[0] == "연면적"][0]
    assert area[1:] == ("200㎡ 미만", "1000㎡ 이하", "연면적 200㎡ 미만")
    assert list(wb["미매핑값"].iter_rows(min_row=2, values_only=True)) == [("구조", "철골철근콘크리트구조", 2)]


def test_excel_without_not_eligible_and_test_mode():
    df, n, o = result_df(test_mode=True)
    wb = load_workbook(io.BytesIO(to_excel_bytes(df, ExportSummary("r", EVAL, n, o, test_mode=True), include_not_eligible=False)))
    assert "비해당" not in wb.sheetnames
    summary = {r[0]: r[1] for r in wb["요약"].iter_rows(min_row=2, values_only=True)}
    assert "시험용" in summary["시험용 적용"]
    assert wb["1차후보"]["A1"].value == "시험용"


def test_export_filename():
    assert export_filename("종로구", ["청운동"], EVAL) == "종로구_청운동_20261115_판정결과.xlsx"
    assert export_filename("종로구", ["청운동", "신교동"], EVAL) == "종로구_2개동_20261115_판정결과.xlsx"
