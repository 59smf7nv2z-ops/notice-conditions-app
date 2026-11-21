from datetime import date

import pandas as pd
import pytest

from core import building_api
from core.conditions import BusinessType, NoticeConditions
from core.notices import condition_hash, load_notices, notices_for
from core.pipeline import run_region

EVAL = date(2026, 11, 15)


def raw_df(n: int, bjd: str) -> pd.DataFrame:
    rows = [
        {
            "mgmBldrgstPk": f"{bjd}{i}", "platPlc": "가상", "newPlatPlc": "", "bldNm": "", "dongNm": "",
            "mainAtchGbCdNm": "주건축물", "regstrGbCdNm": "일반", "regstrKindCdNm": "일반건축물",
            "strctCdNm": "벽돌구조", "etcStrct": "", "mainPurpsCdNm": "단독주택", "etcPurps": "",
            "grndFlrCnt": 2, "ugrndFlrCnt": 0, "totArea": 100.0 + i * 50, "useAprDay": "19800101",
            "hhldCnt": 1, "fmlyCnt": 0, "sigunguCd": "11110", "bjdongCd": bjd, "platGbCd": "0", "bun": "1", "ji": "0",
        }
        for i in range(n)
    ]
    return pd.DataFrame(rows)


class FakeFetch:
    def __init__(self, data: dict[str, pd.DataFrame], fail: dict[str, Exception] | None = None):
        self.data, self.fail, self.calls = data, fail or {}, []

    def __call__(self, sgg, bjd):
        self.calls.append(bjd)
        if bjd in self.fail:
            raise self.fail[bjd]
        df = self.data[bjd]
        return building_api.DongResult(df, len(df), 1, 0.01, [], [])


NOTICE = NoticeConditions(notice_id="t", business_type=BusinessType.APPLY_INSPECTION, min_years=30, max_area=200, area_bound="LT")


def test_cache_skips_refetch_and_accumulates():
    fetch = FakeFetch({"10100": raw_df(3, "10100"), "10200": raw_df(2, "10200")})
    cache: dict = {}
    r1 = run_region("11110", ["10100"], NOTICE, None, EVAL, cache, fetch=fetch)
    assert r1.stats["TOTAL"] == 3 and r1.api_calls == 1
    r2 = run_region("11110", ["10100", "10200"], NOTICE, None, EVAL, cache, fetch=fetch)
    assert fetch.calls == ["10100", "10200"]  # 10100은 다시 조회하지 않음
    assert r2.stats["TOTAL"] == 5 and r2.api_calls == 1
    assert set(cache) == {("11110", "10100"), ("11110", "10200")}


def test_condition_change_reevaluates_without_fetch():
    fetch = FakeFetch({"10100": raw_df(4, "10100")})  # 연면적 100, 150, 200, 250
    cache: dict = {}
    results: dict = {}
    r1 = run_region("11110", ["10100"], NOTICE, None, EVAL, cache, fetch=fetch, results_cache=results)
    assert r1.stats["CANDIDATE"] == 2
    loose = NOTICE.model_copy(update={"area_bound": "LE"})
    r2 = run_region("11110", ["10100"], loose, None, EVAL, cache, fetch=fetch, results_cache=results)
    assert fetch.calls == ["10100"]
    assert r2.stats["CANDIDATE"] == 3  # 200㎡ 이하로 바꾸면 1건 늘어남
    assert r1.condition_hash != r2.condition_hash
    assert len(results) == 2


def test_one_dong_failure_continues():
    fetch = FakeFetch({"10200": raw_df(2, "10200")}, fail={"10100": building_api.BuildingApiServerError("503", "x")})
    r = run_region("11110", ["10100", "10200"], NOTICE, None, EVAL, {}, fetch=fetch)
    assert list(r.failed_dongs) == ["10100"]
    assert r.stats["TOTAL"] == 2


def test_quota_error_stops_and_returns_partial():
    fetch = FakeFetch(
        {"10100": raw_df(2, "10100")},
        fail={"10200": building_api.BuildingApiQuotaError("22", "quota")},
    )
    r = run_region("11110", ["10100", "10200", "10300"], NOTICE, None, EVAL, {}, fetch=fetch)
    assert r.quota_stopped
    assert fetch.calls == ["10100", "10200"]  # 10300은 부르지 않음
    assert set(r.failed_dongs) == {"10200", "10300"}
    assert r.stats["TOTAL"] == 2


def test_auth_error_is_raised():
    fetch = FakeFetch({}, fail={"10100": building_api.BuildingApiAuthError("30", "bad key")})
    with pytest.raises(building_api.BuildingApiAuthError):
        run_region("11110", ["10100"], NOTICE, None, EVAL, {}, fetch=fetch)


def test_test_mode_marks_all_rows():
    fetch = FakeFetch({"10100": raw_df(2, "10100")})
    r = run_region("11110", ["10100"], NOTICE, None, EVAL, {}, fetch=fetch, test_mode=True)
    assert r.df["test_mode"].all()


def test_progress_reported():
    seen = []
    fetch = FakeFetch({"10100": raw_df(1, "10100")})
    run_region("11110", ["10100"], NOTICE, None, EVAL, {}, progress=lambda f, t: seen.append(f), fetch=fetch)
    assert seen[-1] == 1.0


def test_notice_loader_and_selection(tmp_path):
    assert load_notices(tmp_path) == []  # 저장된 공고 없음(데모 공고는 지웠다)
    (tmp_path / "gj.json").write_text(
        NoticeConditions(notice_id="gj", sigungu_codes=["12210"]).model_dump_json(), encoding="utf-8"
    )
    ns = load_notices(tmp_path)
    assert notices_for("12210", ns)[0].notice_id == "gj" and ns[0].reviewed is False
    assert notices_for("11110", ns) == []

    a = NoticeConditions(notice_id="a", sigungu_codes=["11110"], apply_start=date(2025, 3, 1))
    b = NoticeConditions(notice_id="b", sigungu_codes=["11110"], apply_start=date(2026, 3, 1))
    c = NoticeConditions(notice_id="c", sigungu_codes=["11110"])
    assert [n.notice_id for n in notices_for("11110", [a, c, b])] == ["b", "a", "c"]


def test_condition_hash_stable():
    assert condition_hash(NOTICE, None, EVAL) == condition_hash(NOTICE.model_copy(), None, EVAL)
    assert condition_hash(NOTICE, None, EVAL) != condition_hash(NOTICE, None, date(2026, 1, 1))
