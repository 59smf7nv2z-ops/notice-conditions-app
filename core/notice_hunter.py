"""공고 자동 탐색 (단계 7-1, 후순위).

순서: data/notices의 검수된 공고 → 네이버 검색(뉴스 + 웹문서) → 없으면 조례 기준 판정 + 수동 업로드 안내.

- 검색 결과는 후보 링크 목록(제목, 출처, 날짜)으로만 보여 준다. 사용자가 고른 링크만 본문을 가져와 단계 6 분류·추출로 넘긴다.
- 자동 추출 결과는 검수 없이 저장하지 않는다(reviewed=False).
- 뉴스·보도자료 출처는 source_type=NEWS/PRESS_RELEASE로 표시하고 '원문 공고 확인 필요' 경고.
- robots.txt와 접근 제한을 존중한다. 첨부파일(HWP/PDF)은 링크만 보여 주고 사용자가 내려받아 업로드한다.

네이버 검색 API 설정
- 키를 발급받은 곳에 따라 엔드포인트·인증 헤더가 다르다 → NAVER_API_STYLE=developers | hub
- developers(네이버 개발자센터): 아래 NAVER_DEVELOPERS 값. ※ 공식 문서를 자동으로 읽지 못해(접근 차단)
  알려진 형식으로 넣었다. 실제 키로 응답을 확인하기 전까지 '확인 필요'.
- hub(NAVER API HUB): 사용자가 준 공식 가이드 PDF('뉴스 검색 결과 조회', 2026-11-15)로 확인한 값.
  GET https://naverapihub.apigw.ntruss.com/search/v1/news, 헤더 X-NCP-APIGW-API-KEY-ID / X-NCP-APIGW-API-KEY,
  파라미터 query, display(1~100), start(1~1000), sort(sim|date), format(json|xml). 응답 items: title, originallink,
  link, description(<b> 강조), pubDate. 오류 SE01~SE06(400), SE05(404), SE99(500).
  웹문서 검색 엔드포인트는 가이드가 없어 NAVER_HUB_WEB_URL을 넣었을 때만 쓴다(없으면 뉴스만).
- 하루 호출 한도 25,000회(가이드 기준, 검색 API 공통). 한 번 찾기에 최대 6회(쿼리 3개 × 뉴스·웹).
"""

from __future__ import annotations

import html
import os
import re
from dataclasses import dataclass, field
from datetime import date
from email.utils import parsedate_to_datetime
from urllib import robotparser
from urllib.parse import urljoin, urlparse

import requests
from dotenv import load_dotenv

from core.conditions import NoticeConditions
from core.llm.base import LLMProvider, Part
from core.notices import load_notices, notices_for

USER_AGENT = "notice-conditions-bot/0.1 (+municipal building safety tool)"
TIMEOUT = 15
MAX_PAGE_BYTES = 3 * 1024 * 1024
DAILY_LIMIT = 25_000
ATTACHMENT_RE = re.compile(r"\.(hwpx?|pdf|zip|docx?|xlsx?)(\?|$)", re.I)
NEWS_HOST_HINT = ("news", "press", "media", "yna.co.kr", "newsis", "news1")

# 네이버 개발자센터 검색 API (확인 필요: 공식 문서 미확인, 실제 응답으로 검증할 것)
NAVER_DEVELOPERS = {
    "news_url": "https://openapi.naver.com/v1/search/news.json",
    "web_url": "https://openapi.naver.com/v1/search/webkr.json",
    "id_header": "X-Naver-Client-Id",
    "secret_header": "X-Naver-Client-Secret",
    "extra_params": {},
}

# NAVER API HUB 검색 (공식 가이드 PDF로 확인). web_url은 가이드가 없어 비움
NAVER_HUB = {
    "news_url": "https://naverapihub.apigw.ntruss.com/search/v1/news",
    "web_url": "",
    "id_header": "X-NCP-APIGW-API-KEY-ID",
    "secret_header": "X-NCP-APIGW-API-KEY",
    "extra_params": {"format": "json"},
}


class HunterError(RuntimeError):
    pass


class NotConfigured(HunterError):
    """키나 엔드포인트 설정이 없다."""


@dataclass
class Candidate:
    title: str
    url: str
    source: str  # 도메인
    date: str  # YYYY-MM-DD 또는 ""
    kind: str  # news | web
    snippet: str = ""

    @property
    def source_type(self) -> str:
        if self.kind == "news":
            return "NEWS"
        if any(h in self.source for h in NEWS_HOST_HINT):
            return "PRESS_RELEASE"
        return "OFFICIAL_NOTICE"


@dataclass
class HuntResult:
    stage: str  # reviewed | search | none
    notices: list[NoticeConditions] = field(default_factory=list)
    candidates: list[Candidate] = field(default_factory=list)
    message: str = ""
    calls: int = 0


# ---------------------------------------------------------------- 네이버 검색


def _clean(text: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", text or "")).strip()


def naver_config() -> dict:
    load_dotenv()
    style = (os.environ.get("NAVER_API_STYLE") or "developers").strip().lower()
    cid = (os.environ.get("NAVER_CLIENT_ID") or "").strip()
    secret = (os.environ.get("NAVER_CLIENT_SECRET") or "").strip()
    if style == "hub":
        cfg = dict(NAVER_HUB)
        for key in ("news_url", "web_url", "id_header", "secret_header"):  # 가이드가 바뀌면 .env로 덮어쓴다
            override = (os.environ.get(f"NAVER_HUB_{key.upper()}") or "").strip()
            if override:
                cfg[key] = override
    elif style == "developers":
        cfg = dict(NAVER_DEVELOPERS)
    else:
        raise NotConfigured(f"NAVER_API_STYLE은 developers 또는 hub: {style}")
    missing = [n for n, v in (("NAVER_CLIENT_ID", cid), ("NAVER_CLIENT_SECRET", secret)) if not v]
    if missing:
        raise NotConfigured(f".env에 {', '.join(missing)}가 비어 있습니다(Client ID와 Client Secret 둘 다 필요).")
    cfg.update(style=style, id=cid, secret=secret)
    return cfg


def _naver_date(item: dict) -> str:
    raw = item.get("pubDate") or item.get("postdate") or ""
    if re.fullmatch(r"\d{8}", raw):
        return f"{raw[:4]}-{raw[4:6]}-{raw[6:]}"
    try:
        return parsedate_to_datetime(raw).date().isoformat()
    except (TypeError, ValueError):
        return ""


def parse_naver(payload: dict, kind: str) -> list[Candidate]:
    out = []
    for it in payload.get("items") or []:
        url = it.get("originallink") or it.get("link") or ""
        if not url.startswith("http"):
            continue
        out.append(
            Candidate(
                title=_clean(it.get("title", "")),
                url=url,
                source=urlparse(url).netloc,
                date=_naver_date(it),
                kind=kind,
                snippet=_clean(it.get("description", ""))[:200],
            )
        )
    return out


def queries_for(region_name: str, today: date) -> list[str]:
    base = f"{region_name} 소규모 노후건축물 안전점검"
    return [base, f"{today.year}년 {base}", f"{today.year} {region_name} 노후건축물 안전점검 신청"]


def search_candidates(region_name: str, today: date, session: requests.Session | None = None, display: int = 20) -> tuple[list[Candidate], int]:
    cfg = naver_config()
    session = session or requests.Session()
    headers = {cfg["id_header"]: cfg["id"], cfg["secret_header"]: cfg["secret"]}
    seen: dict[str, Candidate] = {}
    calls = 0
    endpoints = [("news", cfg["news_url"], {"sort": "date"}), ("web", cfg["web_url"], {})]
    for q in queries_for(region_name, today):
        for kind, url, extra in endpoints:
            if not url:
                continue  # 웹문서 엔드포인트가 설정되지 않음(HUB)
            params = {"query": q, "display": display, "start": 1, **cfg.get("extra_params", {}), **extra}
            r = session.get(url, params=params, headers=headers, timeout=TIMEOUT)
            calls += 1
            if r.status_code in (401, 403):
                raise HunterError("네이버 검색 인증 실패: Client ID·Secret과 NAVER_API_STYLE을 확인하세요.")
            if r.status_code == 429:
                raise HunterError("네이버 검색 호출 한도를 넘었습니다.")
            if r.status_code >= 400:
                code = ""
                try:
                    body = r.json()
                    code = body.get("errorCode") or (body.get("error") or {}).get("errorCode") or ""
                except (ValueError, AttributeError):
                    pass
                raise HunterError(f"네이버 검색 오류(HTTP {r.status_code}{' ' + str(code) if code else ''})")
            for c in parse_naver(r.json(), kind):
                seen.setdefault(c.url, c)
    cands = sorted(seen.values(), key=lambda c: c.date or "", reverse=True)
    return cands, calls


# ---------------------------------------------------------------- 본문 가져오기


@dataclass
class PageContent:
    url: str
    text: str
    attachments: list[tuple[str, str]]  # (링크 글자, 절대 URL) — 내려받지 않는다


def robots_allows(url: str, session: requests.Session | None = None) -> bool:
    p = urlparse(url)
    robots = f"{p.scheme}://{p.netloc}/robots.txt"
    rp = robotparser.RobotFileParser()
    try:
        r = (session or requests).get(robots, headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT)
    except requests.RequestException:
        return True  # robots.txt를 못 읽으면 일반 규칙대로 허용
    if r.status_code in (401, 403):
        return False
    if r.status_code >= 400:
        return True
    rp.parse(r.text.splitlines())
    return rp.can_fetch(USER_AGENT, url)


def html_to_text(raw: str) -> str:
    raw = re.sub(r"(?is)<(script|style|noscript|nav|footer|header)[^>]*>.*?</\1>", " ", raw)
    raw = re.sub(r"(?i)<br\s*/?>|</(p|div|tr|li|h\d|table)>", "\n", raw)
    raw = re.sub(r"(?i)</t[dh]>", " | ", raw)
    text = html.unescape(re.sub(r"<[^>]+>", " ", raw))
    lines = [re.sub(r"[ \t ]+", " ", ln).strip(" |") for ln in text.splitlines()]
    return "\n".join(ln for ln in lines if ln)


def find_attachments(raw: str, base_url: str) -> list[tuple[str, str]]:
    out = []
    for href, label in re.findall(r'(?is)<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', raw):
        label_text = _clean(label)
        if ATTACHMENT_RE.search(href) or ATTACHMENT_RE.search(label_text) or "download" in href.lower() or "fileDown" in href:
            out.append((label_text or href, urljoin(base_url, html.unescape(href))))
    return list(dict.fromkeys(out))


def fetch_page(url: str, session: requests.Session | None = None) -> PageContent:
    if not url.startswith(("http://", "https://")):
        raise HunterError("http(s) 링크만 가져옵니다.")
    session = session or requests.Session()
    if not robots_allows(url, session):
        raise HunterError("이 사이트의 robots.txt가 자동 수집을 허용하지 않습니다. 직접 열어 확인하세요.")
    r = session.get(url, headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT, stream=True)
    if r.status_code in (401, 403):
        raise HunterError("접근이 제한된 페이지입니다. 직접 열어 확인하세요.")
    if r.status_code >= 400:
        raise HunterError(f"페이지를 가져오지 못했습니다(HTTP {r.status_code}).")
    ctype = r.headers.get("Content-Type", "")
    if "html" not in ctype and "text" not in ctype:
        raise HunterError("HTML 페이지가 아닙니다(첨부파일은 내려받아 직접 업로드하세요).")
    body = r.raw.read(MAX_PAGE_BYTES + 1, decode_content=True)
    if len(body) > MAX_PAGE_BYTES:
        raise HunterError("페이지가 너무 큽니다.")
    raw = body.decode(r.encoding or r.apparent_encoding or "utf-8", errors="replace")
    return PageContent(url=url, text=html_to_text(raw), attachments=find_attachments(raw, url))


def page_parts(page: PageContent) -> list[Part]:
    return [Part.of_text(f"[웹 페이지: {urlparse(page.url).netloc}]\n{page.text[:60_000]}", name=page.url)]


def extract_from_candidate(cand: Candidate, provider: LLMProvider, session: requests.Session | None = None):
    """고른 링크 하나 → 본문 → 분류·추출. 결과는 reviewed=False(검수 전 저장 금지)."""
    from core.llm import extractor

    page = fetch_page(cand.url, session)
    parts = page_parts(page)
    c = extractor.classify(parts, provider)
    if not c.is_apply_inspection:
        return page, c, None
    r = extractor.extract(parts, provider)
    st = cand.source_type
    if st in ("NEWS", "PRESS_RELEASE") or r.notice.source_type in ("NEWS", "PRESS_RELEASE"):
        r.notice = r.notice.model_copy(update={"source_type": st if st != "OFFICIAL_NOTICE" else r.notice.source_type})
        r.issues.insert(0, "뉴스·보도자료 출처입니다. 원문 공고를 확인하세요")
    r.notice = r.notice.model_copy(update={"reviewed": False})
    return page, c, r


# ---------------------------------------------------------------- 전체 순서


def hunt(sigungu_cd: str, region_name: str, today: date, has_ordinance: bool, session: requests.Session | None = None) -> HuntResult:
    reviewed = [n for n in notices_for(sigungu_cd, load_notices()) if n.reviewed]
    if reviewed:
        return HuntResult("reviewed", notices=reviewed, message=f"검수된 공고 {len(reviewed)}건이 있습니다.")
    try:
        cands, calls = search_candidates(region_name, today, session)
    except NotConfigured as e:
        return HuntResult("none", message=f"네이버 검색을 쓸 수 없습니다({e}). " + _fallback(has_ordinance))
    if cands:
        return HuntResult("search", candidates=cands, calls=calls, message=f"검색 후보 {len(cands)}건. 링크를 골라 본문을 가져오세요.")
    return HuntResult("none", calls=calls, message="검색 결과가 없습니다. " + _fallback(has_ordinance))


def _fallback(has_ordinance: bool) -> str:
    base = "조례 기준으로 판정합니다" if has_ordinance else "법정 기준(30년)으로 판정합니다"
    return base + ". 공고 파일이 있으면 아래 '공고 파일 올려 조건 추출'에서 직접 올려 주세요."
