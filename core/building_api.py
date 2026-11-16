"""건축물대장 표제부 법정동 단위 일괄 조회 (인메모리).

서비스: 공공데이터포털 "국토교통부_건축HUB_건축물대장정보 서비스", 오퍼레이션 getBrTitleInfo
근거: 건축HUB OpenAPI 활용가이드 1.0(2024.10)과 실제 호출(2026-11-15, 서울 종로구 청운동).

- (sigunguCd, bjdongCd) → 그 법정동 전체 표제부 DataFrame. bun·ji는 넘기지 않는다.
- core는 순수 함수다. 파일·DB에 저장하지 않는다. 캐시는 호출 측(st.session_state["raw"])이 맡는다.
- 로그·예외 메시지에 주소를 남기지 않는다(코드·건수·소요시간만).

실제 호출로 확인한 사항(2026-11-15)
- numOfRows는 100을 넘겨 요청해도 100건만 온다 → MAX_ROWS = 100 (가이드의 "최대 100건"과 같음)
- body.totalCount는 문자열, 0건이면 items = {"item": []}
- 1건이면 items.item 이 dict → 항상 list로 정규화
- 잘못된 키: HTTP 403 + JSON {"OpenAPI_ServiceResponse": {"cmmMsgHeader": {"returnReasonCode": "30", ...}}}
- mgmBldrgstPk는 JSON 숫자로 오고 길이가 9~22자리로 섞여 있다 → 문자열로 보관
- 문자열 필드의 빈 값은 공백 한 칸(" ")으로 온다 → strip
- 광주 동구: 새 코드 12210은 조회됨, 옛 코드 29110은 0건 (전남광주통합특별시 코드 사용)
"""

from __future__ import annotations

import json
import math
import os
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Callable

import pandas as pd
import requests
from dotenv import load_dotenv
from tenacity import Retrying, retry_if_exception_type, stop_after_attempt, wait_exponential

BASE_URL = "https://apis.data.go.kr/1613000/BldRgstHubService"
OPERATION = "getBrTitleInfo"
MAX_ROWS = 100  # 실제 호출로 확인
DEFAULT_CONCURRENCY = 3  # 페이지 병렬 수. 가이드상 초당 최대 30 tps
TIMEOUT = 30
# 초당 허용량 초과(23)·timeout·5xx·빈 응답에서 지수 백오프로 재시도.
# 계획은 '최대 3회'였으나, 실제 호출(2026-11-15)에서 503 SERVICETIMEOUT_ERROR와 HTTP 200 빈 본문이
# 연달아 3~4번 나온 뒤 정상 응답이 왔다 → 5회로 늘림(최악 약 25초 대기).
MAX_RETRIES = 5
MAX_ATTEMPTS = 1 + MAX_RETRIES
RETRY_WAIT = wait_exponential(multiplier=1, min=1, max=10)  # 1, 2, 4초… 테스트에서 바꿀 수 있게 모듈 변수

COLUMNS = [
    "mgmBldrgstPk", "platPlc", "newPlatPlc", "bldNm", "dongNm", "mainAtchGbCdNm",
    "regstrGbCdNm", "regstrKindCdNm", "strctCdNm", "etcStrct", "mainPurpsCdNm", "etcPurps",
    "grndFlrCnt", "ugrndFlrCnt", "totArea", "useAprDay", "hhldCnt", "fmlyCnt",
    "sigunguCd", "bjdongCd", "platGbCd", "bun", "ji",
]
NUMERIC_COLUMNS = ("grndFlrCnt", "ugrndFlrCnt", "totArea", "hhldCnt", "fmlyCnt")

ProgressFn = Callable[[int, int], None]


# ---------------------------------------------------------------- 예외


class BuildingApiError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(f"건축물대장 API 오류({code}): {message}")
        self.code = code


class BuildingApiQuotaError(BuildingApiError):
    """일일 허용량 초과(22). 즉시 멈추고, 이미 받은 동은 호출 측이 유지한다."""


class BuildingApiRateLimitError(BuildingApiError):
    """초당 허용량 초과(23). 백오프 후 재시도."""


class BuildingApiAuthError(BuildingApiError):
    """서비스키 문제(미등록·만료 등). 재시도하지 않는다."""


class BuildingApiServerError(BuildingApiError):
    """5xx·응답 형식 오류. 백오프 후 재시도."""


AUTH_CODES = {"20", "30", "31", "32", "33"}  # 접근 거부, 미등록 키, 기한 만료, 미등록 IP, 서명 오류
RETRYABLE = (BuildingApiRateLimitError, BuildingApiServerError, requests.Timeout, requests.ConnectionError)


def api_key() -> str:
    load_dotenv()
    key = (os.environ.get("BUILDING_API_KEY") or "").strip()
    if not key:
        raise BuildingApiAuthError("NO_KEY", ".env에 BUILDING_API_KEY(공공데이터포털 Decoding 키)가 없습니다.")
    return key


# ---------------------------------------------------------------- 응답 해석


def _raise_for_code(code: str, message: str) -> None:
    if code in ("00", "0"):
        return
    if code == "22":
        raise BuildingApiQuotaError(code, "일일 허용 호출량을 초과했습니다. 내일 다시 조회하거나 허용량을 늘리세요.")
    if code == "23":
        raise BuildingApiRateLimitError(code, "초당 허용 호출량을 초과했습니다.")
    if code in AUTH_CODES:
        raise BuildingApiAuthError(code, f"서비스키 문제: {message}")
    raise BuildingApiError(code, message or "알 수 없는 오류")


def _parse_xml(text: str) -> dict:
    """_type=json이어도 게이트웨이 오류는 XML로 올 수 있다."""
    try:
        root = ET.fromstring(text)
    except ET.ParseError as e:
        raise BuildingApiServerError("PARSE", "응답이 JSON도 XML도 아닙니다.") from e
    code = root.findtext(".//returnReasonCode") or root.findtext(".//resultCode") or ""
    msg = root.findtext(".//returnAuthMsg") or root.findtext(".//errMsg") or root.findtext(".//resultMsg") or ""
    _raise_for_code(code.strip(), msg.strip())
    raise BuildingApiServerError("PARSE", "XML 응답을 받았지만 오류 코드가 없습니다(JSON 응답 기대).")


def parse_response(status: int, text: str) -> tuple[list[dict], int]:
    """HTTP 응답 → (item 목록, totalCount). 오류면 예외."""
    if status == 429:
        raise BuildingApiRateLimitError("429", "호출이 너무 많습니다(HTTP 429).")
    if status >= 500:
        # 실제 사례(2026-11-15): HTTP 503 + {"OpenAPI_ServiceResponse": {"cmmMsgHeader": {"errMsg": "SERVICETIMEOUT_ERROR", ...}}}
        # 일시적인 게이트웨이 오류였고 몇 초 뒤 정상 → 재시도 대상
        detail = ""
        try:
            h = json.loads(text).get("OpenAPI_ServiceResponse", {}).get("cmmMsgHeader", {})
            detail = f" {h.get('errMsg', '')}({h.get('returnReasonCode', '')})"
        except (ValueError, AttributeError):
            pass
        raise BuildingApiServerError(str(status), f"서버 오류(HTTP {status}){detail}")
    stripped = text.lstrip()
    if not stripped:
        # 실제 사례: HTTP 200 + 빈 본문(일시적). 재시도 대상
        raise BuildingApiServerError("EMPTY", f"빈 응답(HTTP {status})")
    if stripped.startswith("<"):
        _parse_xml(stripped)
    try:
        data = json.loads(text)
    except ValueError as e:
        raise BuildingApiServerError("PARSE", f"JSON 해석 실패(HTTP {status})") from e

    gw = data.get("OpenAPI_ServiceResponse") if isinstance(data, dict) else None
    if gw:
        h = gw.get("cmmMsgHeader", {})
        _raise_for_code(str(h.get("returnReasonCode", "")).strip(), str(h.get("returnAuthMsg") or h.get("errMsg") or ""))
        raise BuildingApiError(str(status), "게이트웨이 오류 응답")

    resp = data.get("response") if isinstance(data, dict) else None
    if not resp:
        raise BuildingApiServerError("PARSE", "response 요소가 없습니다.")
    header = resp.get("header", {})
    _raise_for_code(str(header.get("resultCode", "")).strip(), str(header.get("resultMsg", "")))
    if status >= 400:
        raise BuildingApiError(str(status), f"HTTP {status}")

    body = resp.get("body") or {}
    total = int(str(body.get("totalCount") or 0).strip() or 0)
    items = body.get("items")
    if not items or not isinstance(items, dict):  # "", None, {}
        return [], total
    item = items.get("item")
    if not item:
        return [], total
    return ([item] if isinstance(item, dict) else list(item)), total


# ---------------------------------------------------------------- 호출


def fetch_page(
    session: requests.Session, sigungu_cd: str, bjdong_cd: str, page: int, rows: int = MAX_ROWS, key: str | None = None
) -> tuple[list[dict], int]:
    """한 페이지. 초당 허용량 초과·timeout·5xx는 지수 백오프로 최대 MAX_ATTEMPTS회."""
    params = {
        "serviceKey": key or api_key(),  # Decoding 키를 params로 → requests가 한 번만 인코딩
        "sigunguCd": sigungu_cd,
        "bjdongCd": bjdong_cd,
        "numOfRows": rows,
        "pageNo": page,
        "_type": "json",
    }
    for attempt in Retrying(
        retry=retry_if_exception_type(RETRYABLE),
        stop=stop_after_attempt(MAX_ATTEMPTS),
        wait=RETRY_WAIT,
        reraise=True,
    ):
        with attempt:
            r = session.get(f"{BASE_URL}/{OPERATION}", params=params, timeout=TIMEOUT)
            return parse_response(r.status_code, r.text)
    raise AssertionError("unreachable")


def _clean(v: object) -> object:
    return v.strip() if isinstance(v, str) else v


def to_dataframe(items: list[dict]) -> tuple[pd.DataFrame, list[str]]:
    """item 목록 → 반환 컬럼 DataFrame. 실제 응답에 없는 필드 이름도 돌려준다."""
    present = set().union(*(i.keys() for i in items)) if items else set(COLUMNS)
    missing = [c for c in COLUMNS if c not in present]
    rows = [{c: _clean(i.get(c, "")) for c in COLUMNS} for i in items]
    df = pd.DataFrame(rows, columns=COLUMNS).astype({c: "object" for c in COLUMNS})
    for c in NUMERIC_COLUMNS:
        df[c] = pd.to_numeric(df[c], errors="coerce")  # 변환 실패는 NaN
    for c in ("mgmBldrgstPk", "useAprDay", "sigunguCd", "bjdongCd", "platGbCd", "bun", "ji"):
        df[c] = df[c].map(lambda v: "" if v is None or (isinstance(v, float) and math.isnan(v)) else str(v)).astype("object")
    return df, missing


@dataclass
class DongResult:
    df: pd.DataFrame
    total_count: int
    api_calls: int
    seconds: float
    missing_fields: list[str]
    warnings: list[str]


def fetch_dong(
    sigungu_cd: str,
    bjdong_cd: str,
    *,
    session: requests.Session | None = None,
    concurrency: int = DEFAULT_CONCURRENCY,
    progress: ProgressFn | None = None,
    key: str | None = None,
) -> DongResult:
    """법정동 하나의 표제부 전체. 일일 허용량 초과면 BuildingApiQuotaError를 그대로 올린다."""
    t0 = time.perf_counter()
    session = session or requests.Session()
    key = key or api_key()
    first, total = fetch_page(session, sigungu_cd, bjdong_cd, 1, MAX_ROWS, key)
    pages = max(1, math.ceil(total / MAX_ROWS))
    calls, done = 1, 1
    if progress:
        progress(done, pages)
    items = list(first)
    if pages > 1:
        with ThreadPoolExecutor(max_workers=max(1, concurrency)) as ex:
            futures = {ex.submit(fetch_page, session, sigungu_cd, bjdong_cd, p, MAX_ROWS, key): p for p in range(2, pages + 1)}
            results: dict[int, list[dict]] = {}
            try:
                for f in as_completed(futures):
                    page_items, _ = f.result()
                    results[futures[f]] = page_items
                    calls += 1
                    done += 1
                    if progress:
                        progress(done, pages)
            except BuildingApiQuotaError:
                for f in futures:
                    f.cancel()
                raise
        for p in sorted(results):
            items += results[p]

    warnings: list[str] = []
    seen: set[str] = set()
    unique = []
    for i in items:
        pk = str(i.get("mgmBldrgstPk", ""))
        if pk and pk in seen:
            continue
        seen.add(pk)
        unique.append(i)
    if len(unique) != len(items):
        warnings.append(f"중복 PK {len(items) - len(unique)}건 제거")
    if len(unique) != total:
        warnings.append(f"totalCount {total}건과 받은 건수 {len(unique)}건이 다릅니다(조회 중 대장 갱신 가능)")
    df, missing = to_dataframe(unique)
    return DongResult(df, total, calls, time.perf_counter() - t0, missing, warnings)


def estimate_calls(
    sigungu_cd: str, bjdong_cds: list[str], *, session: requests.Session | None = None, key: str | None = None
) -> dict:
    """numOfRows=1로 동별 totalCount만 받아 예상 호출 수를 계산한다(UI 경고용).

    반환: {"per_dong": {bjdongCd: 건수}, "buildings": 합계, "calls": 본 조회 예상 호출 수, "probe_calls": 이번에 쓴 호출 수}
    """
    session = session or requests.Session()
    key = key or api_key()
    per = {}
    for b in bjdong_cds:
        _, total = fetch_page(session, sigungu_cd, b, 1, 1, key)
        per[b] = total
    return {
        "per_dong": per,
        "buildings": sum(per.values()),
        "calls": sum(max(1, math.ceil(t / MAX_ROWS)) for t in per.values()),
        "probe_calls": len(bjdong_cds),
    }


# ---------------------------------------------------------------- PNU


PLAT_GB_TO_PNU = {"0": "1", "1": "2"}  # 대장 대지구분(0 대지, 1 산, 2 블록) → PNU 토지구분(1 일반, 2 산)


def make_pnu(row: dict | pd.Series) -> str | None:
    """19자리 PNU = sigunguCd + bjdongCd + 토지구분 + 본번 4자리 + 부번 4자리.

    블록 지번(platGbCd=2)이나 번·지가 숫자가 아니면 None (지도 단계에서 '좌표 없음'으로 처리).
    """
    sgg = str(row.get("sigunguCd", "")).strip()
    bjd = str(row.get("bjdongCd", "")).strip()
    land = PLAT_GB_TO_PNU.get(str(row.get("platGbCd", "")).strip())
    bun = str(row.get("bun", "")).strip() or "0"
    ji = str(row.get("ji", "")).strip() or "0"
    if not (len(sgg) == 5 and len(bjd) == 5 and land and bun.isdigit() and ji.isdigit()):
        return None
    if len(bun) > 4 or len(ji) > 4:
        return None
    return f"{sgg}{bjd}{land}{int(bun):04d}{int(ji):04d}"
