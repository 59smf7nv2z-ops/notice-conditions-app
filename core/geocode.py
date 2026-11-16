"""브이월드 지오코더 API 2.0 — 판정 결과 건물 좌표.

- 대상: CANDIDATE, NEEDS_CHECK (옵션으로 ORDINANCE_ONLY). NOT_ELIGIBLE은 지오코딩하지 않는다.
- 1순위 지번주소(platPlc, type=parcel), 실패 시 도로명주소(newPlatPlc, type=road).
- 같은 PNU(필지)는 한 번만 호출한다. 한 필지에 여러 동이 있으면 지도 마커 하나에 목록으로 넣는다.
- 브이월드 이용약관: 응답을 저장장치·DB에 저장할 수 없다 → 캐시는 호출 측이 넘기는 dict
  (st.session_state["geo"])만 쓴다. 파일 캐시 금지. 로그에 주소를 남기지 않는다.

실제 호출로 확인한 응답(2026-11-15)
- OK:        {"response": {"status": "OK", "result": {"crs": "EPSG:4326", "point": {"x": "126.97", "y": "37.57"}}, ...}}
- 못 찾음:   {"response": {"status": "NOT_FOUND", ...}}
- 키 오류:   {"response": {"status": "ERROR", "error": {"level": "2", "code": "INVALID_KEY", "text": "..."}}}
- 대장 platPlc 형식("○○동 2번지")을 그대로 넣어도 찾는다.
"""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Callable

import pandas as pd
import requests
from dotenv import load_dotenv
from tenacity import Retrying, retry_if_exception_type, stop_after_attempt, wait_exponential

from core.building_api import make_pnu

GEOCODER_URL = "https://api.vworld.kr/req/address"
DEFAULT_CONCURRENCY = 5
TIMEOUT = 15
MAX_ATTEMPTS = 4
RETRY_WAIT = wait_exponential(multiplier=1, min=1, max=8)
DAILY_LIMIT = 40_000  # 브이월드 지오코더 일일 최대 호출

DEFAULT_STATUSES = ("CANDIDATE", "NEEDS_CHECK")
AUTH_ERROR_CODES = {"INVALID_KEY", "INCORRECT_KEY", "UNAVAILABLE_KEY", "OVER_REQUEST_LIMIT"}

ProgressFn = Callable[[int, int], None]


class GeocodeError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(f"브이월드 지오코더 오류({code}): {message}")
        self.code = code


class GeocodeAuthError(GeocodeError):
    """키 오류·일일 한도 초과 등. 더 부르지 않고 멈춘다."""


class _Retryable(GeocodeError):
    pass


def geocoder_key() -> str:
    load_dotenv()
    key = (os.environ.get("VWORLD_GEOCODER_KEY") or "").strip()
    if not key:
        raise GeocodeAuthError("NO_KEY", ".env에 VWORLD_GEOCODER_KEY가 없습니다.")
    return key


def parse_geocode(status_code: int, payload: dict) -> tuple[float, float] | None:
    """응답 → (위도, 경도). 못 찾으면 None. 오류면 예외."""
    if status_code >= 500:
        raise _Retryable(str(status_code), f"서버 오류(HTTP {status_code})")
    resp = payload.get("response") or {}
    status = resp.get("status")
    if status == "OK":
        p = (resp.get("result") or {}).get("point") or {}
        try:
            return float(p["y"]), float(p["x"])
        except (KeyError, TypeError, ValueError) as e:
            raise GeocodeError("PARSE", "좌표가 없습니다.") from e
    if status == "NOT_FOUND":
        return None
    err = resp.get("error") or {}
    code = str(err.get("code") or status or status_code)
    if code in AUTH_ERROR_CODES:
        raise GeocodeAuthError(code, str(err.get("text") or ""))
    raise _Retryable(code, str(err.get("text") or "알 수 없는 오류"))


def geocode_address(session: requests.Session, address: str, type_: str, key: str) -> tuple[float, float] | None:
    params = {
        "service": "address",
        "request": "getcoord",
        "version": "2.0",
        "crs": "epsg:4326",
        "address": address,
        "refine": "true",
        "simple": "false",
        "format": "json",
        "type": type_,
        "key": key,
    }
    for attempt in Retrying(
        retry=retry_if_exception_type((_Retryable, requests.Timeout, requests.ConnectionError)),
        stop=stop_after_attempt(MAX_ATTEMPTS),
        wait=RETRY_WAIT,
        reraise=True,
    ):
        with attempt:
            r = session.get(GEOCODER_URL, params=params, timeout=TIMEOUT)
            try:
                payload = r.json()
            except ValueError as e:
                raise _Retryable("PARSE", f"JSON이 아닌 응답(HTTP {r.status_code})") from e
            return parse_geocode(r.status_code, payload)
    raise AssertionError("unreachable")


def parcel_key(row: dict | pd.Series) -> str:
    """같은 필지는 한 번만 부르기 위한 키. PNU를 못 만들면(블록 지번 등) 건물 단위."""
    pnu = make_pnu(row)
    return pnu if pnu else f"pk:{row.get('mgmBldrgstPk', '')}"


def _clean(v: object) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ""
    return str(v).strip()


@dataclass
class GeocodeResult:
    calls: int = 0
    found: int = 0
    not_found: list[str] = field(default_factory=list)  # 필지 키
    errors: dict[str, str] = field(default_factory=dict)
    stopped: str | None = None  # 키 오류 등으로 멈춘 경우 사유


def targets(df: pd.DataFrame, statuses: tuple[str, ...] = DEFAULT_STATUSES) -> pd.DataFrame:
    return df[df["status"].isin(statuses)]


def pending_parcels(df: pd.DataFrame, cache: dict, statuses: tuple[str, ...] = DEFAULT_STATUSES) -> dict[str, dict]:
    """아직 캐시에 없는 필지 → 대표 행(주소). 예상 호출 수 안내용."""
    out: dict[str, dict] = {}
    for row in targets(df, statuses).to_dict("records"):
        k = parcel_key(row)
        if k not in cache and k not in out:
            out[k] = row
    return out


def geocode_buildings(
    df: pd.DataFrame,
    cache: dict,
    *,
    statuses: tuple[str, ...] = DEFAULT_STATUSES,
    concurrency: int = DEFAULT_CONCURRENCY,
    progress: ProgressFn | None = None,
    session: requests.Session | None = None,
    key: str | None = None,
) -> GeocodeResult:
    """판정 결과의 대상 건물 좌표를 cache[필지키] = {"lat","lng","type"} | None 로 채운다."""
    todo = pending_parcels(df, cache, statuses)
    result = GeocodeResult()
    if not todo:
        return result
    key = key or geocoder_key()
    session = session or requests.Session()

    def work(row: dict) -> tuple[dict | None, int]:
        calls = 0
        for addr, type_ in ((_clean(row.get("platPlc")), "parcel"), (_clean(row.get("newPlatPlc")), "road")):
            if not addr:
                continue
            calls += 1
            point = geocode_address(session, addr, type_, key)
            if point:
                return {"lat": point[0], "lng": point[1], "type": type_}, calls
        return None, calls

    done = 0
    with ThreadPoolExecutor(max_workers=max(1, concurrency)) as ex:
        futures = {ex.submit(work, row): k for k, row in todo.items()}
        for f in as_completed(futures):
            k = futures[f]
            done += 1
            try:
                value, calls = f.result()
            except GeocodeAuthError as e:
                result.stopped = str(e)
                for other in futures:
                    other.cancel()
                break
            except Exception as e:  # noqa: BLE001 - 필지 하나 실패는 기록하고 계속
                result.errors[k] = str(e)
                continue
            result.calls += calls
            cache[k] = value
            if value:
                result.found += 1
            else:
                result.not_found.append(k)
            if progress:
                progress(done, len(todo))
    return result


def attach_coords(df: pd.DataFrame, cache: dict) -> pd.DataFrame:
    """parcel_key, lat, lng, geo_status('OK' | '좌표 없음' | '미조회') 컬럼을 붙인 사본."""
    out = df.copy()
    keys = [parcel_key(r) for r in out.to_dict("records")]
    out["parcel_key"] = keys
    lat, lng, st = [], [], []
    for k in keys:
        if k not in cache:
            lat.append(None), lng.append(None), st.append("미조회")
        elif cache[k] is None:
            lat.append(None), lng.append(None), st.append("좌표 없음")
        else:
            lat.append(cache[k]["lat"]), lng.append(cache[k]["lng"]), st.append("OK")
    out["lat"], out["lng"], out["geo_status"] = lat, lng, st
    return out
