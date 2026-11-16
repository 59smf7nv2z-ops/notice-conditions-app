"""Streamlit 화면 자동 점검(AppTest). 외부 API(건축물대장·브이월드·LLM)는 모두 가짜로 바꾼다.

화면을 사람이 눌러 보기 전에 '예외 없이 그려지는지', '조회 → 판정 → 안내문·지도'가 이어지는지를 잡는다.
"""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from core import boundaries, building_api

APP = str(Path(__file__).resolve().parents[1] / "app" / "main.py")


def fake_items(bjd: str) -> list[dict]:
    base = {
        "platPlc": "가상시 가상구 가상동 {n}번지", "newPlatPlc": "", "bldNm": "", "dongNm": "",
        "mainAtchGbCdNm": "주건축물", "regstrGbCdNm": "일반", "regstrKindCdNm": "일반건축물",
        "strctCdNm": "벽돌구조", "etcStrct": "", "mainPurpsCdNm": "단독주택", "etcPurps": "주택",
        "grndFlrCnt": 2, "ugrndFlrCnt": 0, "hhldCnt": 1, "fmlyCnt": 0,
        "sigunguCd": "11110", "bjdongCd": bjd, "platGbCd": "0", "ji": "0",
    }
    rows = []
    for n, (apr, area) in enumerate([("19800101", 120.0), ("", 90.0), ("20150101", 100.0), ("19750505", 900.0)], 1):
        rows.append(dict(base, platPlc=base["platPlc"].format(n=n), useAprDay=apr, totArea=area, bun=str(n),
                         mgmBldrgstPk=f"{bjd}{n:04d}"))
    return rows


@pytest.fixture
def fakes(monkeypatch):
    calls = []

    def fetch_dong(sgg, bjd, **kw):
        calls.append(bjd)
        df, missing = building_api.to_dataframe(fake_items(bjd))
        return building_api.DongResult(df, len(df), 1, 0.01, missing, [])

    square = {"type": "FeatureCollection", "features": [{
        "type": "Feature", "properties": {"sig_cd": "11110", "emd_cd": "11110101", "full_nm": "가상동"},
        "geometry": {"type": "MultiPolygon", "coordinates": [[[[126.96, 37.58], [126.98, 37.58], [126.98, 37.60], [126.96, 37.58]]]]},
    }]}
    monkeypatch.setattr(building_api, "fetch_dong", fetch_dong)
    monkeypatch.setattr(building_api, "api_key", lambda: "TEST")
    monkeypatch.setattr(boundaries, "sigungu_boundary", lambda *a, **k: square)
    monkeypatch.setattr(boundaries, "emd_boundaries", lambda *a, **k: square)
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    return calls


def run_query(at: AppTest) -> AppTest:
    at.run()
    assert not at.exception
    next(b for b in at.button if b.label == "조회·판정").click().run()
    assert not at.exception
    return at


def metric(at: AppTest, label: str) -> str:
    return next(m.value for m in at.metric if m.label == label)


def test_first_screen_renders_without_network(fakes):
    at = AppTest.from_file(APP, default_timeout=60)
    at.run()
    assert not at.exception
    assert at.segmented_control[0].value == "region"
    assert fakes == []  # 누르기 전에는 조회하지 않는다


def test_query_judge_and_rerun_without_refetch(fakes):
    at = run_query(AppTest.from_file(APP, default_timeout=60))
    assert fakes == ["10100"]
    assert metric(at, "총 건물 수") == "4"
    # 조례(종로구, 규모 수치 없음) 기준: 30년 이상 2건 후보, 사용승인일 공란 1건 확인필요, 2015년 1건 비해당
    assert (metric(at, "1차 후보"), metric(at, "확인필요"), metric(at, "비해당")) == ("2", "1", "1")
    at.run()  # 다시 그려도 재조회하지 않음
    assert fakes == ["10100"] and not at.exception
    assert any(d.label == "Excel 내려받기" for d in at.download_button)


def test_letters_and_map_sections_use_session_result(fakes):
    at = run_query(AppTest.from_file(APP, default_timeout=60))
    at.segmented_control[0].set_value("letters").run()
    assert not at.exception
    assert any("1건 미리보기" in m.value for m in at.markdown)
    assert any("안내문 docx" in d.label for d in at.download_button)
    at.segmented_control[0].set_value("map").run()
    assert not at.exception
    assert any("지도 좌표 가져오기" in b.label for b in at.button)  # 좌표는 버튼을 눌러야 가져온다
    assert fakes == ["10100"]


def test_notice_section_renders(fakes):
    at = AppTest.from_file(APP, default_timeout=60)
    at.run()
    at.segmented_control[0].set_value("notice").run()
    assert not at.exception
    heads = [s.value for s in at.subheader]
    assert "공고 파일 올려 조건 추출" in heads and "이 지역 공고 찾기" in heads and "저장된 공고 보기" in heads


def test_missing_building_key_shows_error(fakes, monkeypatch):
    def no_key():
        raise building_api.BuildingApiAuthError("NO_KEY", ".env에 BUILDING_API_KEY가 없습니다.")

    monkeypatch.setattr(building_api, "api_key", no_key)
    at = AppTest.from_file(APP, default_timeout=60)
    at.run()
    assert not at.exception
    assert any("BUILDING_API_KEY" in e.value for e in at.error)
