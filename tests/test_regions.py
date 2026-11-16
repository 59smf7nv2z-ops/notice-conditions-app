import warnings

from core import regions


def test_find_cheongun_dong():
    code = regions.find_code("서울특별시 종로구 청운동")
    assert code == "1111010100"
    assert ("10100", "청운동") in regions.list_bjdong("11110")
    assert regions.name_of("1111010100") == "서울특별시 종로구 청운동"
    assert regions.name_of("11110") == "서울특별시 종로구"


def test_incheon_new_districts_listed():
    names = {name for _, name in regions.list_sigungu("인천광역시")}
    expected = {"제물포구", "영종구", "검단구", "서해구"}
    missing = expected - names
    if missing:
        warnings.warn(f"법정동코드 파일이 오래된 것 같습니다. 인천 개편 구 없음: {missing}")
    assert not missing
    assert not {"중구", "동구", "서구"} & names  # 폐지된 구는 목록에 없음


def test_sido_list_has_merged_and_special():
    sidos = regions.list_sido()
    assert "전남광주통합특별시" in sidos
    assert "세종특별자치시" in sidos
    assert "광주광역시" not in sidos and "전라남도" not in sidos
    assert regions.list_sigungu("세종") == [("36110", "세종특별자치시")]


def test_general_gu_city_uses_gu_codes():
    sgg = dict(regions.list_sigungu("경기도"))
    assert "41110" not in sgg  # 수원시 자체 코드는 빼고
    assert sgg["41111"] == "수원시 장안구"  # 구 코드를 쓴다
    assert regions.parent_city_children()["경기도 수원시"] == ("41111", "41113", "41115", "41117")
    # 4자리가 같아도 부모·자식이 아닌 경우(영동군 43740, 증평군 43745)는 그대로
    cb = dict(regions.list_sigungu("충청북도"))
    assert "43740" in cb and "43745" in cb


def test_ri_listed_instead_of_myeon():
    rows = regions.list_bjdong("41830")  # 경기도 양평군
    codes = {c for c, _ in rows}
    assert "25000" not in codes  # 양평읍 자체는 빼고
    assert ("25021", "양평읍 양근리") in rows


def test_match_sigungu_kinds():
    assert regions.match_sigungu("서울시", "종로구") == {"codes": ["11110"], "kind": "exact", "abolished": []}
    assert regions.match_sigungu("경기도", "수원시")["kind"] == "parent_city"
    gwangju = regions.match_sigungu("광주광역시", "동구")
    assert gwangju["kind"] == "abolished" and gwangju["codes"] == [] and gwangju["abolished"] == ["29110"]
    assert regions.match_sigungu("없는도", "없는구")["kind"] == "none"
