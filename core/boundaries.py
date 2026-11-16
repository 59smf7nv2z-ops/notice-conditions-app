"""브이월드 2D 데이터 API 2.0 — 행정경계 GeoJSON.

레이어(실제 호출로 확인, 2026-11-15)
- 시군구 LT_C_ADSIGG_INFO: sig_cd(5자리), sig_kor_nm, full_nm
- 읍면동 LT_C_ADEMD_INFO: emd_cd(8자리 = sigunguCd + bjdongCd 앞 3자리), emd_kor_nm, full_nm
- 리     LT_C_ADRI_INFO:   li_cd(10자리 = 법정동코드), li_kor_nm, full_nm
- 새 코드(전남광주통합특별시 12210, 인천 제물포구 28125, 수원시 장안구 41111)로 조회됨. 옛 코드 29110은 NOT_FOUND.
- attrFilter: "emd_cd:=:11110101", "emd_cd:like:11110". like는 부분 일치라 결과를 코드 앞자리로 다시 거른다.
- geometry=true면 EPSG:4326 MultiPolygon. size 최대 1000.

캐시: 호출 측이 넘기는 dict(세션)만 쓴다.
TODO: 브이월드 이용약관에서 경계 데이터의 저장이 허용되는지 확인되면 data/cache/boundaries/ 파일 캐시를
      옵션으로 추가한다. 확인 전에는 구현하지 않는다.
"""

from __future__ import annotations

import os

import requests
from dotenv import load_dotenv
from tenacity import Retrying, retry_if_exception_type, stop_after_attempt, wait_exponential

DATA_URL = "https://api.vworld.kr/req/data"
TIMEOUT = 30
PAGE_SIZE = 1000
MAX_ATTEMPTS = 4
RETRY_WAIT = wait_exponential(multiplier=1, min=1, max=8)

SIGUNGU, EMD, RI = "LT_C_ADSIGG_INFO", "LT_C_ADEMD_INFO", "LT_C_ADRI_INFO"
CODE_FIELD = {SIGUNGU: "sig_cd", EMD: "emd_cd", RI: "li_cd"}
NAME_FIELD = {SIGUNGU: "sig_kor_nm", EMD: "emd_kor_nm", RI: "li_kor_nm"}


class BoundaryError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(f"브이월드 2D 데이터 오류({code}): {message}")
        self.code = code


class _Retryable(BoundaryError):
    pass


def data_key() -> str:
    load_dotenv()
    key = (os.environ.get("VWORLD_DATA_KEY") or "").strip()
    if not key:
        raise BoundaryError("NO_KEY", ".env에 VWORLD_DATA_KEY가 없습니다.")
    return key


def empty_fc() -> dict:
    return {"type": "FeatureCollection", "features": []}


def _get(session: requests.Session, params: dict) -> dict:
    for attempt in Retrying(
        retry=retry_if_exception_type((_Retryable, requests.Timeout, requests.ConnectionError)),
        stop=stop_after_attempt(MAX_ATTEMPTS),
        wait=RETRY_WAIT,
        reraise=True,
    ):
        with attempt:
            r = session.get(DATA_URL, params=params, timeout=TIMEOUT)
            if r.status_code >= 500:
                raise _Retryable(str(r.status_code), "서버 오류")
            try:
                return r.json().get("response") or {}
            except ValueError as e:
                raise _Retryable("PARSE", f"JSON이 아닌 응답(HTTP {r.status_code})") from e
    raise AssertionError("unreachable")


def fetch_layer(
    layer: str,
    attr_filter: str,
    *,
    code_prefix: str | None = None,
    cache: dict | None = None,
    session: requests.Session | None = None,
    key: str | None = None,
) -> dict:
    """레이어 조회 → FeatureCollection. code_prefix가 있으면 코드 앞자리로 다시 거른다(like 부분 일치 보정)."""
    ck = (layer, attr_filter, code_prefix)
    if cache is not None and ck in cache:
        return cache[ck]
    key = key or data_key()
    session = session or requests.Session()
    features: list[dict] = []
    page = 1
    while True:
        resp = _get(
            session,
            {
                "service": "data",
                "request": "GetFeature",
                "data": layer,
                "format": "json",
                "geometry": "true",
                "attribute": "true",
                "crs": "EPSG:4326",
                "attrFilter": attr_filter,
                "size": str(PAGE_SIZE),
                "page": str(page),
                "key": key,
            },
        )
        status = resp.get("status")
        if status == "NOT_FOUND":
            break
        if status != "OK":
            err = resp.get("error") or {}
            raise BoundaryError(str(err.get("code") or status), str(err.get("text") or ""))
        fc = (resp.get("result") or {}).get("featureCollection") or {}
        features += fc.get("features") or []
        total_pages = int(((resp.get("page") or {}).get("total")) or 1)
        if page >= total_pages:
            break
        page += 1
    if code_prefix:
        field = CODE_FIELD[layer]
        features = [f for f in features if str(f.get("properties", {}).get(field, "")).startswith(code_prefix)]
    out = {"type": "FeatureCollection", "features": features}
    if cache is not None:
        cache[ck] = out
    return out


def sigungu_boundary(sigungu_cd: str, **kw) -> dict:
    return fetch_layer(SIGUNGU, f"sig_cd:=:{sigungu_cd}", **kw)


def emd_boundaries(sigungu_cd: str, **kw) -> dict:
    """시군구 안의 읍면동 경계 전체."""
    return fetch_layer(EMD, f"emd_cd:like:{sigungu_cd}", code_prefix=sigungu_cd, **kw)


def ri_boundaries(emd_cd: str, **kw) -> dict:
    """읍·면(8자리) 안의 리 경계."""
    return fetch_layer(RI, f"li_cd:like:{emd_cd}", code_prefix=emd_cd, **kw)


def emd_code(sigungu_cd: str, bjdong_cd: str) -> str:
    """대장 법정동(5자리) → 읍면동 경계 코드(8자리)."""
    return f"{sigungu_cd}{bjdong_cd[:3]}"
