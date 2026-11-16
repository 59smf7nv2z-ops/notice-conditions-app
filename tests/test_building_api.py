"""건축물대장 표제부 조회 테스트 (requests 모킹). 실제 호출은 live 마크."""

import pytest
import requests
import responses
from responses import matchers
from tenacity import wait_none

from core import building_api as api

URL = f"{api.BASE_URL}/{api.OPERATION}"
KEY = "TEST-KEY"


@pytest.fixture(autouse=True)
def no_wait(monkeypatch):
    monkeypatch.setattr(api, "RETRY_WAIT", wait_none())


def item(pk: int, **kw) -> dict:
    base = {
        "rnum": pk, "platPlc": "가상 주소", "newPlatPlc": " ", "bldNm": " ", "dongNm": " ",
        "mainAtchGbCdNm": "주건축물", "regstrGbCdNm": "일반", "regstrKindCdNm": "일반건축물",
        "strctCdNm": "벽돌구조", "etcStrct": "벽돌구조", "mainPurpsCdNm": "단독주택", "etcPurps": "주택",
        "grndFlrCnt": 2, "ugrndFlrCnt": 0, "totArea": 120.5, "useAprDay": "19850301",
        "hhldCnt": 1, "fmlyCnt": 0, "sigunguCd": "11110", "bjdongCd": "10100",
        "platGbCd": "0", "bun": "0012", "ji": "0003", "mgmBldrgstPk": 1000000000000000000000 + pk,
    }
    base.update(kw)
    return base


def ok_body(items, total, rows=100, page=1) -> dict:
    if items is None:
        items_el = ""
    elif isinstance(items, dict):
        items_el = {"item": items}
    else:
        items_el = {"item": items}
    return {
        "response": {
            "header": {"resultCode": "00", "resultMsg": "NORMAL SERVICE"},
            "body": {"items": items_el, "numOfRows": rows, "pageNo": page, "totalCount": str(total)},
        }
    }


def gw_error(code: str, name: str) -> dict:
    return {"OpenAPI_ServiceResponse": {"cmmMsgHeader": {"errMsg": name, "returnAuthMsg": name, "returnReasonCode": code}}}


def page_matcher(page: int, rows: int = 100):
    return matchers.query_param_matcher({"pageNo": str(page), "numOfRows": str(rows)}, strict_match=False)


# ---------------------------------------------------------------- 응답 해석


@responses.activate
@pytest.mark.parametrize("items_el", [{"item": []}, "", None])
def test_zero_results(items_el):
    body = ok_body([], 0)
    body["response"]["body"]["items"] = items_el
    responses.get(URL, json=body)
    r = api.fetch_dong("11110", "10100", key=KEY)
    assert r.total_count == 0 and len(r.df) == 0 and r.api_calls == 1
    assert list(r.df.columns) == api.COLUMNS


@responses.activate
def test_single_item_dict_normalized_to_list():
    responses.get(URL, json=ok_body(item(1), 1))
    r = api.fetch_dong("11110", "10100", key=KEY)
    assert len(r.df) == 1
    row = r.df.iloc[0]
    assert row.mgmBldrgstPk == "1000000000000000000001"  # 22자리 PK를 문자열로
    assert row.newPlatPlc == ""  # 공백 한 칸 → 빈 문자열
    assert row.useAprDay == "19850301"
    assert row.totArea == 120.5


@responses.activate
def test_multiple_pages_and_progress():
    total = 250
    all_items = [item(i) for i in range(1, total + 1)]
    for p in (1, 2, 3):
        chunk = all_items[(p - 1) * 100 : p * 100]
        responses.get(URL, json=ok_body(chunk, total, page=p), match=[page_matcher(p)])
    seen = []
    r = api.fetch_dong("11110", "10100", key=KEY, progress=lambda d, t: seen.append((d, t)))
    assert len(r.df) == 250 and r.api_calls == 3 and r.warnings == []
    assert seen[0] == (1, 3) and seen[-1] == (3, 3)
    assert r.df.mgmBldrgstPk.is_unique


@responses.activate
def test_numeric_conversion_failure_is_nan():
    responses.get(URL, json=ok_body([item(1, grndFlrCnt="", totArea="abc")], 1))
    row = api.fetch_dong("11110", "10100", key=KEY).df.iloc[0]
    assert row.grndFlrCnt != row.grndFlrCnt  # NaN
    assert row.totArea != row.totArea


@responses.activate
def test_missing_fields_reported():
    it = item(1)
    del it["dongNm"]
    responses.get(URL, json=ok_body([it], 1))
    r = api.fetch_dong("11110", "10100", key=KEY)
    assert r.missing_fields == ["dongNm"]
    assert r.df.iloc[0].dongNm == ""


@responses.activate
def test_count_mismatch_warning():
    responses.get(URL, json=ok_body([item(1)], 2))
    r = api.fetch_dong("11110", "10100", key=KEY)
    assert any("totalCount" in w for w in r.warnings)


# ---------------------------------------------------------------- 오류 처리


@responses.activate
def test_daily_quota_22_stops_immediately():
    responses.get(URL, json=gw_error("22", "LIMITED_NUMBER_OF_SERVICE_REQUESTS_EXCEEDS_ERROR"))
    with pytest.raises(api.BuildingApiQuotaError):
        api.fetch_dong("11110", "10100", key=KEY)
    assert len(responses.calls) == 1  # 재시도하지 않음


@responses.activate
def test_quota_on_later_page_raises():
    responses.get(URL, json=ok_body([item(i) for i in range(1, 101)], 150), match=[page_matcher(1)])
    responses.get(URL, json=gw_error("22", "LIMITED"), match=[page_matcher(2)])
    with pytest.raises(api.BuildingApiQuotaError):
        api.fetch_dong("11110", "10100", key=KEY)


@responses.activate
def test_rate_limit_23_then_success():
    responses.get(URL, json=gw_error("23", "LIMITED_NUMBER_OF_SERVICE_REQUESTS_PER_SECOND_EXCEEDS_ERROR"))
    responses.get(URL, json=ok_body([item(1)], 1))
    r = api.fetch_dong("11110", "10100", key=KEY)
    assert len(r.df) == 1 and len(responses.calls) == 2


@responses.activate
def test_rate_limit_gives_up_after_max_attempts():
    for _ in range(api.MAX_ATTEMPTS):
        responses.get(URL, json=gw_error("23", "PER_SECOND"))
    with pytest.raises(api.BuildingApiRateLimitError):
        api.fetch_dong("11110", "10100", key=KEY)
    assert len(responses.calls) == api.MAX_ATTEMPTS


@responses.activate
def test_server_error_then_success():
    responses.get(URL, status=502, body="Bad Gateway")
    responses.get(URL, json=ok_body([item(1)], 1))
    assert len(api.fetch_dong("11110", "10100", key=KEY).df) == 1


@responses.activate
def test_gateway_flakiness_seen_in_real_calls():
    # 2026-11-15 실제 관찰: 503 SERVICETIMEOUT_ERROR → 200 빈 본문 → 정상
    responses.get(URL, status=503, json=gw_error("04", "SERVICETIMEOUT_ERROR"))
    responses.get(URL, status=503, json=gw_error("04", "SERVICETIMEOUT_ERROR"))
    responses.get(URL, status=200, body="")
    responses.get(URL, json=ok_body([item(1)], 1))
    assert len(api.fetch_dong("11110", "10100", key=KEY).df) == 1
    assert len(responses.calls) == 4


@responses.activate
def test_timeout_then_success():
    responses.get(URL, body=requests.Timeout())
    responses.get(URL, json=ok_body([item(1)], 1))
    assert len(api.fetch_dong("11110", "10100", key=KEY).df) == 1


@responses.activate
def test_xml_error_even_with_type_json():
    xml = (
        "<OpenAPI_ServiceResponse><cmmMsgHeader><errMsg>SERVICE ERROR</errMsg>"
        "<returnAuthMsg>SERVICE_KEY_IS_NOT_REGISTERED_ERROR</returnAuthMsg>"
        "<returnReasonCode>30</returnReasonCode></cmmMsgHeader></OpenAPI_ServiceResponse>"
    )
    responses.get(URL, body=xml, status=200, content_type="text/xml")
    with pytest.raises(api.BuildingApiAuthError):
        api.fetch_dong("11110", "10100", key=KEY)
    assert len(responses.calls) == 1


@responses.activate
def test_unregistered_key_403_json():
    # 실제 응답 형태(2026-11-15 확인)
    responses.get(URL, status=403, json=gw_error("30", "SERVICE_KEY_IS_NOT_REGISTERED_ERROR"))
    with pytest.raises(api.BuildingApiAuthError) as e:
        api.fetch_dong("11110", "10100", key=KEY)
    assert e.value.code == "30"


@responses.activate
def test_result_code_error_in_header():
    body = ok_body([], 0)
    body["response"]["header"] = {"resultCode": "03", "resultMsg": "NODATA_ERROR"}
    responses.get(URL, json=body)
    with pytest.raises(api.BuildingApiError) as e:
        api.fetch_dong("11110", "10100", key=KEY)
    assert e.value.code == "03"


def test_error_message_has_no_address():
    e = api.BuildingApiQuotaError("22", "x")
    assert "22" in str(e)


@responses.activate
def test_decoding_key_sent_once_encoded():
    responses.get(URL, json=ok_body([], 0))
    api.fetch_dong("11110", "10100", key="abc+/=")
    url = responses.calls[0].request.url
    assert "serviceKey=abc%2B%2F%3D" in url  # 한 번만 인코딩(%252B 아님)


def test_missing_key_raises(monkeypatch):
    monkeypatch.setattr(api, "load_dotenv", lambda *a, **k: None)
    monkeypatch.delenv("BUILDING_API_KEY", raising=False)
    with pytest.raises(api.BuildingApiAuthError):
        api.api_key()


# ---------------------------------------------------------------- 예상 호출 수, PNU


@responses.activate
def test_estimate_calls():
    responses.get(URL, json=ok_body([item(1)], 359, rows=1), match=[matchers.query_param_matcher({"bjdongCd": "10100"}, strict_match=False)])
    responses.get(URL, json=ok_body([], 0, rows=1), match=[matchers.query_param_matcher({"bjdongCd": "10200"}, strict_match=False)])
    est = api.estimate_calls("11110", ["10100", "10200"], key=KEY)
    assert est == {"per_dong": {"10100": 359, "10200": 0}, "buildings": 359, "calls": 5, "probe_calls": 2}
    assert all("numOfRows=1&" in c.request.url or c.request.url.endswith("numOfRows=1") for c in responses.calls)


@pytest.mark.parametrize(
    "row, expected",
    [
        ({"sigunguCd": "11110", "bjdongCd": "10100", "platGbCd": "0", "bun": "0012", "ji": "0003"}, "1111010100100120003"),
        ({"sigunguCd": "11110", "bjdongCd": "10100", "platGbCd": "1", "bun": "12", "ji": ""}, "1111010100200120000"),
        ({"sigunguCd": "11110", "bjdongCd": "10100", "platGbCd": "2", "bun": "12", "ji": "0"}, None),  # 블록
        ({"sigunguCd": "11110", "bjdongCd": "10100", "platGbCd": "0", "bun": "가", "ji": "0"}, None),
    ],
)
def test_make_pnu(row, expected):
    pnu = api.make_pnu(row)
    assert pnu == expected
    if pnu:
        assert len(pnu) == 19


# ---------------------------------------------------------------- 실제 호출 (기본 skip)


@pytest.mark.live
def test_live_cheongun():
    from core import regions

    code = regions.find_code("서울특별시 종로구 청운동")
    r = api.fetch_dong(code[:5], code[5:])
    assert r.total_count > 300  # 2026-11-15 기준 359건(대장 갱신으로 달라질 수 있음)
    assert len(r.df) == r.total_count
    assert r.missing_fields == []
