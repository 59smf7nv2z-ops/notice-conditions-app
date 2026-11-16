"""조례 분류 스크립트(scripts/classify_ordinances.py) 테스트.

원문을 직접 읽어 확인한 값을 고정해, 규칙을 고칠 때 이미 맞던 분류가 깨지지 않게 한다.
"""

from pathlib import Path

import pytest

import classify_ordinances as co

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "ordinances" / "ordinances_raw.csv"


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("5백", 500),
        ("2백", 200),
        ("1천", 1000),
        ("1천500", 1500),
        ("1,000", 1000),
        ("660", 660),
        ("5백 ", 500),
        ("백", 100),
    ],
)
def test_parse_area_korean_numbers(raw, expected):
    assert co.parse_area(raw) == expected


def test_parse_area_unreadable_returns_none():
    assert co.parse_area("오백") is None


@pytest.fixture(scope="module")
def rows():
    return co.classify_file(RAW)


@pytest.fixture(scope="module")
def by_name(rows):
    out = {}
    for r in rows:
        if r["row_role"] == "점검대상":
            assert r["지자체"] not in out, f"점검대상 중복: {r['지자체']}"
            out[r["지자체"]] = r
    return out


def test_row_roles(rows):
    roles = {}
    for r in rows:
        roles[r["row_role"]] = roles.get(r["row_role"], 0) + 1
    assert len(rows) == 225
    assert roles == {"점검대상": 216, "지원조문(점검대상 아님)": 7, "개편전조례(대체됨)": 2}


def test_superseded_incheon_ordinances(rows):
    old = {(r["지자체"], r["ordinance_name"]) for r in rows if r["row_role"] == "개편전조례(대체됨)"}
    assert old == {
        ("인천광역시 제물포구", "인천광역시 동구 건축물관리 조례"),
        ("인천광역시 영종구", "인천광역시 중구 건축물관리 조례"),
    }


def test_every_inspection_row_has_type(by_name):
    assert all(r["scale_rule_type"] for r in by_name.values())


@pytest.mark.parametrize(
    "name, floors, fbound, area, abound",
    [
        ("강원특별자치도 강릉시", "2", "LE", "500", "LT"),  # 2층 이하, 5백 미만
        ("경상북도 경산시", "3", "LE", "1000", "LT"),  # 3층 이하의 1천 미만
        ("경상북도 김천시", "3", "LE", "1500", "LE"),  # 1천500 이하
        ("경기도 부천시", "4", "LE", "660", "LE"),
        ("서울특별시 마포구", "", "", "660", "LE"),  # 층수 없음
        ("전남광주통합특별시 곡성군", "", "", "100", "LT"),
    ],
)
def test_numeric_bounds_keep_le_lt(by_name, name, floors, fbound, area, abound):
    r = by_name[name]
    assert r["scale_rule_type"] == "NUMERIC"
    assert (r["max_floors"], r["floors_bound"], r["max_area"], r["area_bound"]) == (floors, fbound, area, abound)


def test_dangjin_confirmed_min_floors(by_name):
    r = by_name["충청남도 당진시"]
    assert r["scale_rule_type"] == "CONSTRUCTION_ACT_REF"
    assert (r["min_floors"], r["min_floors_bound"]) == ("3", "GE")
    assert r["max_floors"] == ""
    assert r["review_needed"] == ""
    assert r["review_reason"].startswith("검토 확정")


def test_seosan_floor_range(by_name):
    r = by_name["충청남도 서산시"]
    assert (r["min_floors"], r["min_floors_bound"], r["max_floors"], r["floors_bound"]) == ("3", "GE", "10", "LE")
    assert r["review_needed"] == "Y"


def test_external_reference_types_have_no_guessed_numbers(by_name):
    for r in by_name.values():
        if r["scale_rule_type"] in ("STRUCTURE_RULE_REF", "DISCRETION"):
            assert r["max_area"] == "" and r["max_floors"] == "", r["지자체"]


def test_or_definitions_are_discretion_with_reference_note(by_name):
    for name in ("울산광역시 동구", "울산광역시 중구", "경기도 하남시", "경상남도 함양군"):
        r = by_name[name]
        assert r["scale_rule_type"] == "DISCRETION", name
        assert r["note"].startswith("참고 수치"), name


def test_gujojeok_is_not_masonry(by_name):
    # '구조적 균열'의 '조적'을 조적조로 읽던 오류 방지
    assert by_name["서울특별시 동작구"]["structure_filter"] == ""


def test_masonry_and_use_filters(by_name):
    assert by_name["서울특별시 강남구"]["structure_filter"] == "조적조"
    assert by_name["경기도 평택시"]["structure_filter"] == "조적조"  # 벽돌(블럭)
    assert by_name["경기도 여주시"]["use_filter"] == "단독주택(다가구주택 제외)|지역아동센터"


def test_nowon_years_set_yearly(by_name):
    r = by_name["서울특별시 노원구"]
    assert r["min_years"] == ""
    assert "매년" in r["review_reason"]


def test_exclusion_flags(by_name):
    daejeon_dong = by_name["대전광역시 동구"]
    assert daejeon_dong["excl_collective"] == "Y"
    assert daejeon_dong["excl_multi_housing"] == "MANDATORY_MGMT"
    assert daejeon_dong["private_only"] == "Y"
    assert "공공건축물" in daejeon_dong["exclusions"].split(" | ")
    assert by_name["경상남도 함안군"]["excl_multi_housing"] == "ALL"  # 주택법 공동주택 전체


def test_draft_file_is_up_to_date(rows):
    """data/ordinances/ordinance_conditions_draft.csv 가 스크립트 결과와 같은지(재생성 누락 방지)."""
    import csv

    draft = ROOT / "data" / "ordinances" / "ordinance_conditions_draft.csv"
    with open(draft, encoding="utf-8-sig", newline="") as f:
        saved = list(csv.DictReader(f))
    assert saved == rows, "스크립트를 고쳤으면 python scripts/classify_ordinances.py 로 초안을 다시 만드세요"
