"""브이월드 지오코더·행정경계 테스트 (requests 모킹). 실제 호출은 live 마크."""

import pandas as pd
import pytest
import responses
from responses import matchers
from tenacity import wait_none

from core import boundaries, geocode

KEY = "TEST"


@pytest.fixture(autouse=True)
def no_wait(monkeypatch):
    monkeypatch.setattr(geocode, "RETRY_WAIT", wait_none())
    monkeypatch.setattr(boundaries, "RETRY_WAIT", wait_none())


def geo_ok(x: float, y: float) -> dict:
    return {"response": {"status": "OK", "result": {"crs": "EPSG:4326", "point": {"x": str(x), "y": str(y)}}}}


GEO_NOT_FOUND = {"response": {"status": "NOT_FOUND"}}
GEO_BAD_KEY = {"response": {"status": "ERROR", "error": {"level": "2", "code": "INVALID_KEY", "text": "등록되지 않은 인증키입니다."}}}


def addr(a: str, t: str):
    return matchers.query_param_matcher({"address": a, "type": t}, strict_match=False)


def bldg(pk, status, bun, ji="0", plat="0", road="", **kw) -> dict:
    base = {"mgmBldrgstPk": pk, "status": status, "platPlc": f"가상시 가상구 가상동 {bun}번지", "newPlatPlc": road,
            "sigunguCd": "11110", "bjdongCd": "10100", "platGbCd": plat, "bun": bun, "ji": ji}
    base.update(kw)
    return base


# ---------------------------------------------------------------- 지오코더


@responses.activate
def test_parcel_first_then_road_and_same_pnu_once():
    df = pd.DataFrame(
        [
            bldg("1", "CANDIDATE", "1"),
            bldg("2", "NEEDS_CHECK", "1"),  # 같은 필지 → 한 번만 호출
            bldg("3", "CANDIDATE", "2", road="가상로 5"),  # 지번 실패 → 도로명
            bldg("4", "CANDIDATE", "3"),  # 둘 다 실패 → 좌표 없음
            bldg("5", "NOT_ELIGIBLE", "4"),  # 비해당은 지오코딩 안 함
        ]
    )
    responses.get(geocode.GEOCODER_URL, json=geo_ok(126.9, 37.5), match=[addr("가상시 가상구 가상동 1번지", "parcel")])
    responses.get(geocode.GEOCODER_URL, json=GEO_NOT_FOUND, match=[addr("가상시 가상구 가상동 2번지", "parcel")])
    responses.get(geocode.GEOCODER_URL, json=geo_ok(127.0, 37.6), match=[addr("가상로 5", "road")])
    responses.get(geocode.GEOCODER_URL, json=GEO_NOT_FOUND, match=[addr("가상시 가상구 가상동 3번지", "parcel")])
    cache: dict = {}
    seen = []
    r = geocode.geocode_buildings(df, cache, key=KEY, concurrency=1, progress=lambda d, t: seen.append((d, t)))
    assert r.calls == 4 and r.found == 2 and len(r.not_found) == 1
    assert seen[-1] == (3, 3)
    out = geocode.attach_coords(df, cache)
    assert list(out.geo_status) == ["OK", "OK", "OK", "좌표 없음", "미조회"]
    assert (out.lat[0], out.lng[0]) == (37.5, 126.9)
    assert cache["1111010100100020000"]["type"] == "road"  # 대지(0→1) 2번지
    # 다시 부르면 캐시에 있어 호출하지 않음
    assert geocode.geocode_buildings(df, cache, key=KEY).calls == 0
    assert len(responses.calls) == 4


@responses.activate
def test_ordinance_only_optional():
    df = pd.DataFrame([bldg("1", "ORDINANCE_ONLY", "1")])
    assert geocode.pending_parcels(df, {}) == {}
    responses.get(geocode.GEOCODER_URL, json=geo_ok(126.9, 37.5))
    r = geocode.geocode_buildings(df, {}, key=KEY, statuses=("CANDIDATE", "NEEDS_CHECK", "ORDINANCE_ONLY"))
    assert r.found == 1


@responses.activate
def test_invalid_key_stops():
    df = pd.DataFrame([bldg(str(i), "CANDIDATE", str(i)) for i in range(1, 4)])
    responses.get(geocode.GEOCODER_URL, json=GEO_BAD_KEY)
    cache: dict = {}
    r = geocode.geocode_buildings(df, cache, key=KEY, concurrency=1)
    assert r.stopped and "INVALID_KEY" in r.stopped
    assert cache == {}


@responses.activate
def test_server_error_retried():
    df = pd.DataFrame([bldg("1", "CANDIDATE", "1")])
    responses.get(geocode.GEOCODER_URL, status=502, body="bad")
    responses.get(geocode.GEOCODER_URL, json=geo_ok(126.9, 37.5))
    assert geocode.geocode_buildings(df, {}, key=KEY).found == 1


def test_block_lot_uses_building_key():
    row = bldg("77", "CANDIDATE", "1", plat="2")
    assert geocode.parcel_key(row) == "pk:77"


def test_no_file_cache_in_geocode_module():
    import inspect

    src = inspect.getsource(geocode)
    assert "open(" not in src and "to_csv" not in src and "json.dump" not in src


# ---------------------------------------------------------------- 행정경계


def fc_response(features, page_total=1, page=1, status="OK"):
    return {
        "response": {
            "status": status,
            "page": {"total": str(page_total), "current": str(page)},
            "result": {"featureCollection": {"type": "FeatureCollection", "features": features}},
        }
    }


def feat(code_field, code, name):
    return {"type": "Feature", "properties": {code_field: code, "full_nm": name},
            "geometry": {"type": "MultiPolygon", "coordinates": [[[[126.9, 37.5], [127.0, 37.5], [127.0, 37.6], [126.9, 37.5]]]]}}


@responses.activate
def test_emd_boundaries_filters_like_and_pages():
    responses.get(boundaries.DATA_URL, json=fc_response([feat("emd_cd", "11110101", "청운동"), feat("emd_cd", "41111101", "엉뚱")], 2, 1),
                  match=[matchers.query_param_matcher({"page": "1"}, strict_match=False)])
    responses.get(boundaries.DATA_URL, json=fc_response([feat("emd_cd", "11110102", "신교동")], 2, 2),
                  match=[matchers.query_param_matcher({"page": "2"}, strict_match=False)])
    cache: dict = {}
    fc = boundaries.emd_boundaries("11110", cache=cache, key=KEY)
    assert [f["properties"]["emd_cd"] for f in fc["features"]] == ["11110101", "11110102"]
    assert "emd_cd:like:11110" in responses.calls[0].request.url.replace("%3A", ":")
    boundaries.emd_boundaries("11110", cache=cache, key=KEY)  # 세션 캐시
    assert len(responses.calls) == 2


@responses.activate
def test_not_found_is_empty():
    responses.get(boundaries.DATA_URL, json={"response": {"status": "NOT_FOUND"}})
    assert boundaries.sigungu_boundary("29110", key=KEY) == {"type": "FeatureCollection", "features": []}


@responses.activate
def test_boundary_error():
    responses.get(boundaries.DATA_URL, json={"response": {"status": "ERROR", "error": {"code": "INVALID_KEY", "text": "x"}}})
    with pytest.raises(boundaries.BoundaryError):
        boundaries.sigungu_boundary("11110", key=KEY)


def test_emd_code():
    assert boundaries.emd_code("11110", "10100") == "11110101"
    assert boundaries.emd_code("41830", "25021") == "41830250"


# ---------------------------------------------------------------- 실제 호출 (기본 skip)


@pytest.mark.live
def test_live_vworld():
    import requests

    s = requests.Session()
    point = geocode.geocode_address(s, "서울특별시 종로구 청운동 2번지", "parcel", geocode.geocoder_key())
    assert point and 37.5 < point[0] < 37.7 and 126.9 < point[1] < 127.1
    fc = boundaries.sigungu_boundary("11110")
    assert fc["features"] and fc["features"][0]["geometry"]["type"] == "MultiPolygon"
