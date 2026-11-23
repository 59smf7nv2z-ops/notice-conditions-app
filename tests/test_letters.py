import io
from datetime import date

import pandas as pd
import pytest
from docx import Document

from core import letters as L
from core.conditions import BusinessType, Contact, NoticeConditions

NOTICE = NoticeConditions(
    notice_id="t",
    local_gov="가상시 가상구",
    program_name="소규모 노후건축물 안전점검 지원",
    business_type=BusinessType.APPLY_INSPECTION,
    application_period="2026. 7. 1. ~ 2026. 7. 31.",
    apply_start=date(2026, 7, 1),
    apply_end=date(2026, 7, 31),
    contact=Contact(reception="건축과", inquiry="02-000-0000", apply_method="방문 신청", documents=["신청서", "건축물대장"]),
)


def row(status="CANDIDATE", **kw) -> dict:
    base = {"status": status, "platPlc": "가상시 가상구 가상동 1-2", "newPlatPlc": "가상로 3", "useAprDay": "19850301",
            "age_years": 41, "strctCdNm": "벽돌구조", "mainPurpsCdNm": "단독주택", "grndFlrCnt": 2.0, "totArea": 123.456}
    base.update(kw)
    return base


@pytest.mark.parametrize("tone", list(L.TONES))
def test_builtin_templates_pass_validation(tone):
    assert L.validate_template(L.make_template(NOTICE, tone)) == []


def test_validation_catches_problems():
    bad = "{지번주소} {소유자성명} 연면적 200㎡ 이하 건물은 선정되었습니다. {판정안내}\n끝"
    problems = " ".join(L.validate_template(bad))
    assert "{소유자성명}" in problems
    assert "200㎡" in problems
    assert "선정되었습니다" in problems
    assert "발송 전 담당자 검토" in problems
    assert any("판정안내" in p for p in L.validate_template("{지번주소}\n" + L.REVIEW_LINE))


def test_fill_status_phrases_and_values():
    t = L.make_template(NOTICE, "official")
    a = L.fill(t, row("CANDIDATE"), NOTICE)
    b = L.fill(t, row("NEEDS_CHECK"), NOTICE)
    assert "지원 대상에 해당할 가능성이 높습니다" in a
    assert "지원 대상에 해당할 수 있습니다" in b
    assert "가상시 가상구 가상동 1-2 건축물 소유자(관리자)" in a
    assert "1985-03-01" in a and "41년" in a and "123.46㎡" in a and "2층" in a
    assert "신청서, 건축물대장" in a and "가상시 가상구 건축안전센터" in a
    assert "{" not in a
    assert a.strip().splitlines()[-1] == L.REVIEW_LINE
    for word in ("선정되었습니다", "지원 대상입니다"):
        assert word not in a


def test_missing_notice_fields_marked():
    text = L.fill(L.make_template(None, "elder"), row(useAprDay="", age_years=None), None)
    assert L.MISSING in text and "(대장 미기재)" in text and "확인 필요" in text


def test_only_candidate_or_needs_check():
    with pytest.raises(L.LetterBlockedError):
        L.fill(L.make_template(NOTICE, "sms"), row("NOT_ELIGIBLE"), NOTICE)


def test_expired_notice_still_generates_with_closed_line():
    tpl = L.make_template(NOTICE, "elder")
    assert L.closed_line(NOTICE, date(2026, 7, 31)) is None  # 마감일 당일은 접수 중
    open_text = L.fill(tpl, row(), NOTICE, date(2026, 7, 31))
    closed = L.fill(tpl, row(), NOTICE, date(2026, 8, 1))
    assert "마감된 공고" not in open_text
    assert closed.splitlines()[0] == L.closed_line(NOTICE, date(2026, 8, 1)) and "마감 2026-07-31" in closed
    assert closed.endswith(open_text)


def test_sms_bytes():
    assert L.sms_bytes("가나다") == 6 and L.sms_bytes("abc") == 3
    assert L.sms_kind("가" * 45) == "SMS"
    assert L.sms_kind("가" * 46) == "LMS"
    filled = L.fill(L.make_template(NOTICE, "sms"), row(), NOTICE)
    assert L.sms_kind(filled) == "LMS"  # 주소·문의처가 들어가면 보통 90바이트를 넘음


def test_docx_one_page_per_building():
    df = pd.DataFrame([row(), row("NEEDS_CHECK", platPlc="가상시 가상구 가상동 9")])
    doc = Document(io.BytesIO(L.letters_docx(df, L.make_template(NOTICE, "official"), NOTICE)))
    text = "\n".join(p.text for p in doc.paragraphs)
    assert text.count("건축물 소유자(관리자) 귀하") == 2
    breaks = sum(1 for p in doc.paragraphs for r in p.runs if 'w:br' in r._r.xml and 'type="page"' in r._r.xml)
    assert breaks == 1


def test_targets_csv():
    df = pd.DataFrame([row(), row("NEEDS_CHECK")])
    text = L.targets_csv(df).decode("utf-8-sig")
    assert text.splitlines()[0].startswith("수신자,지번주소")
    assert "1차 후보" in text and "확인필요" in text
