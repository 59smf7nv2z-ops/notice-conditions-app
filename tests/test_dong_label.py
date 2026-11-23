from datetime import date

from app.state import Ctx


def _ctx(cds, names, all_sel=False):
    return Ctx(sido="충청북도", sigungu_cd="43111", sigungu_name="청주시 상당구", bjdong_cds=cds,
               bjdong_names=names, all_selected=all_sel, eval_date=date(2026, 1, 1), notice=None,
               notice_edited=False, test_mode=False, ordinance=None)


def test_dong_label():
    names = {"1": "용암동", "2": "금천동", "3": "영운동", "4": "낭성면"}
    assert _ctx([], names).dong_label == ""
    assert _ctx(["1"], names).dong_label == "용암동"
    assert _ctx(["1", "2"], names).dong_label == "용암동·금천동"
    assert _ctx(["1", "2", "3"], names).dong_label == "용암동 외 2곳"
    assert _ctx([], names, all_sel=True).dong_label == "모든 읍·면·동"
    assert _ctx([], {"1": "용암동"}, all_sel=True).dong_label == "모든 동"
