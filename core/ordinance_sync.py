"""조례 동기화 로직 (단계 7-2, 후순위). 운영자 스크립트(scripts/sync_ordinances.py)에서만 쓴다.

법제처 Open API(국가법령정보 공동활용)는 신청 때 등록한 IP에서만 동작한다 → 앱 런타임에서 부르지 않는다.

공식 가이드로 확인한 것(open.law.go.kr ordinListGuide·ordinInfoGuide, 2026-11-15)
- 목록: http://www.law.go.kr/DRF/lawSearch.do?target=ordin  (OC, type=JSON, query, search=1(이름), display≤100, page,
  sort, knd=30001(조례), org·sborg(지자체 코드))
  응답 필드: 자치법규일련번호, 자치법규명, 자치법규ID, 공포일자, 공포번호, 제개정구분명, 지자체기관명, 자치법규종류, 시행일자, 자치법규상세링크
- 본문: http://www.law.go.kr/DRF/lawService.do?target=ordin  (OC, type=JSON, ID 또는 MST)
  조문 필드: 조문번호, 조문여부(Y=조, N=편·장·절), 조제목, 조내용
- 기존 조례 CSV의 조문 칸 '000600Y소규모 … 제6조(…)' = 조문번호 + 조문여부 + 조제목 + 조내용 형태와 같다.

실제 응답으로 확인한 것(2026-11-15, 등록 IP PC에서 호출)
- 목록 JSON: {"OrdinSearch": {"law": [...], "totalCnt", "page", ...}}, 본문 JSON: {"LawService": {"자치법규기본정보", "조문": {"조": [...]}, "부칙"}}
  (바깥 구조가 바뀌어도 되도록 키 이름으로 레코드를 찾는다: find_records)
- 개정할 때마다 자치법규일련번호(MST)는 바뀌고 자치법규ID는 그대로다(종로구 조례 연혁 3건) → ID로 추적, law_ids.csv에 남긴다.
- 조문번호가 ['000500', '000500']처럼 목록으로 온다.
- API 본문의 점검 대상 조문 = 기존 CSV 조문(공백 무시 완전 일치, 종로구).
- '건축물관리 조례'로 찾으면 861건(다른 조례 포함). 이름이 같은 조례만 비교한다.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from pathlib import Path

import requests

LIST_URL = "http://www.law.go.kr/DRF/lawSearch.do"
BODY_URL = "http://www.law.go.kr/DRF/lawService.do"
ORDINANCE_KIND = "30001"  # 조례
TIMEOUT = 30
PAGE_SIZE = 100

ARTICLE_START = re.compile(r"(?m)^[ \t]*제(\d+)조(?:의(\d+))?[ \t]*\(")


class SyncError(RuntimeError):
    pass


def find_records(obj, key: str) -> list[dict]:
    """응답 바깥 구조를 모르므로, key를 가진 dict를 모두 찾는다(중첩 순회)."""
    out: list[dict] = []
    if isinstance(obj, dict):
        if key in obj:
            out.append(obj)
        for v in obj.values():
            if isinstance(v, (dict, list)):
                out += find_records(v, key)
    elif isinstance(obj, list):
        for v in obj:
            out += find_records(v, key)
    return out


# ---------------------------------------------------------------- 조문


@dataclass
class Article:
    number: str  # 조문번호(예: 000600)
    is_article: str  # 조문여부 Y/N
    title: str  # 조제목
    body: str  # 조내용

    @property
    def row_text(self) -> str:
        """기존 조례 CSV 조문 칸과 같은 형태."""
        return f"{self.number}{self.is_article}{self.title}{self.body}"


def split_articles(text: str) -> list[tuple[str, str]]:
    """본문 한 덩어리 → [(조 번호 '6' 또는 '6의2', 조 전체 텍스트)].

    줄 시작의 '제N조(' 만 조의 시작으로 본다. 본문 속 인용('법 제15조제1항')에서는 자르지 않는다.
    """
    starts = list(ARTICLE_START.finditer(text))
    out = []
    for i, m in enumerate(starts):
        end = starts[i + 1].start() if i + 1 < len(starts) else len(text)
        no = m.group(1) + (f"의{m.group(2)}" if m.group(2) else "")
        out.append((no, text[m.start() : end].strip()))
    return out


def _scalar(v) -> str:
    """실제 응답에서 조문번호가 ['000500', '000500']처럼 목록으로 왔다(2026-11-15) → 첫 값."""
    if isinstance(v, list):
        v = next((x for x in v if str(x).strip()), "")
    return str(v or "").strip()


def articles_from_body(payload: dict) -> list[Article]:
    arts = []
    for r in find_records(payload, "조문번호"):
        arts.append(
            Article(
                number=_scalar(r.get("조문번호")),
                is_article=_scalar(r.get("조문여부")) or "Y",
                title=_scalar(r.get("조제목")),
                body=_scalar(r.get("조내용")) if not isinstance(r.get("조내용"), list) else "\n".join(map(str, r["조내용"])),
            )
        )
    return arts


def inspection_article(articles: list[Article]) -> Article | None:
    """'소규모 노후 건축물 등 점검(의) 대상/실시' 조문.

    정기점검·긴급점검 대상 조문과 지원·재정지원 조문은 뺀다(실제 종로구 조례에 '정기점검 대상' 조문이 앞에 있었다).
    """
    for a in articles:
        t = a.title.replace(" ", "")
        if (
            a.is_article == "Y"
            and "점검" in t
            and ("소규모" in t or "노후" in t)
            and ("대상" in t or "실시" in t)
            and "지원" not in t
        ):
            return a
    return None


# ---------------------------------------------------------------- API 호출 (운영자 PC에서만)


def list_ordinances(oc: str, query: str, session: requests.Session | None = None, max_pages: int = 50) -> list[dict]:
    session = session or requests.Session()
    out: list[dict] = []
    for page in range(1, max_pages + 1):
        r = session.get(
            LIST_URL,
            params={"OC": oc, "target": "ordin", "type": "JSON", "query": query, "search": 1,
                    "knd": ORDINANCE_KIND, "display": PAGE_SIZE, "page": page},
            timeout=TIMEOUT,
        )
        if r.status_code >= 400:
            raise SyncError(f"자치법규 목록 조회 실패(HTTP {r.status_code})")
        try:
            payload = r.json()
        except ValueError as e:
            raise SyncError("JSON이 아닌 응답입니다. OC 값과 등록 IP를 확인하세요(법제처 API는 등록한 IP에서만 동작).") from e
        rows = find_records(payload, "자치법규ID")
        out += rows
        if len(rows) < PAGE_SIZE:
            break
    return out


def fetch_body(oc: str, ordin_id: str, session: requests.Session | None = None) -> dict:
    session = session or requests.Session()
    r = session.get(BODY_URL, params={"OC": oc, "target": "ordin", "type": "JSON", "ID": ordin_id}, timeout=TIMEOUT)
    if r.status_code >= 400:
        raise SyncError(f"자치법규 본문 조회 실패(HTTP {r.status_code})")
    try:
        return r.json()
    except ValueError as e:
        raise SyncError("JSON이 아닌 응답입니다.") from e


# ---------------------------------------------------------------- 변경 감지와 제안


def _norm(s: str) -> str:
    return re.sub(r"\s+", "", s or "")


@dataclass
class Change:
    kind: str  # updated | new
    jurisdiction: str  # 지자체
    name: str  # 조례명
    old_date: str
    new_date: str
    ordin_id: str
    serial: str  # 자치법규일련번호(MST)


@dataclass
class ChangeSet:
    changes: list[Change] = field(default_factory=list)
    unchanged: int = 0
    missing: list[tuple[str, str]] = field(default_factory=list)  # 목록에서 못 찾은 기존 조례(폐지·명칭 변경 가능)


def detect_changes(raw_rows: list[dict], listed: list[dict]) -> ChangeSet:
    """기존 조례 원본(ordinances_raw.csv)과 법제처 목록을 시행일자로 비교한다.

    같은 조례 판단: 지자체기관명 + 자치법규명(공백 무시). 한 지자체가 여러 행(지원 조문 등)이면 조례명 기준 한 번만 본다.
    """
    current: dict[tuple[str, str], str] = {}
    for r in raw_rows:
        current.setdefault((_norm(r["지자체"]), _norm(r["조례명"])), r["시행일"].strip())
    seen: set[tuple[str, str]] = set()
    cs = ChangeSet()
    for rec in listed:
        key = (_norm(str(rec.get("지자체기관명", ""))), _norm(str(rec.get("자치법규명", ""))))
        if key in seen:
            continue
        seen.add(key)
        new_date = str(rec.get("시행일자", "")).strip()
        args = dict(jurisdiction=str(rec.get("지자체기관명", "")).strip(), name=str(rec.get("자치법규명", "")).strip(),
                    new_date=new_date, ordin_id=str(rec.get("자치법규ID", "")), serial=str(rec.get("자치법규일련번호", "")))
        if key not in current:
            continue  # 수집 대상(점검 조문이 있는 건축물관리 조례)이 아닐 수 있어 '신규'로 자동 추가하지 않는다
        if current[key] != new_date:
            cs.changes.append(Change(kind="updated", old_date=current[key], **args))
        else:
            cs.unchanged += 1
    cs.missing = [k for k in current if k not in seen]
    return cs


def proposal_rows(change: Change, articles: list[Article]) -> list[dict]:
    """변경된 조례의 새 원본 행(점검 대상 조문). 조문을 못 찾으면 빈 목록."""
    a = inspection_article(articles)
    if a is None:
        return []
    return [{"지자체": change.jurisdiction, "조례명": change.name, "시행일": change.new_date, "조문": a.row_text}]


DIFF_FIELDS = [
    "scale_rule_type", "min_years", "max_floors", "floors_bound", "min_floors", "min_floors_bound", "max_area", "area_bound",
    "use_filter", "structure_filter", "private_only", "excl_collective", "excl_multi_housing", "committee_required",
]


def diff_classified(old: dict | None, new: dict) -> list[tuple[str, str, str]]:
    return [(f, (old or {}).get(f, ""), new.get(f, "")) for f in DIFF_FIELDS if (old or {}).get(f, "") != new.get(f, "")]


def read_csv(path: Path) -> list[dict]:
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def apply_proposal(raw_rows: list[dict], proposal: list[dict], is_inspection_row) -> tuple[list[dict], int]:
    """승인된 제안을 원본에 반영: 같은 (지자체, 조례명)의 점검대상 행을 새 행으로 바꾼다. (결과, 반영 행 수)

    is_inspection_row(row) -> bool: 그 행이 점검 대상 조문인지(지원 조문은 그대로 둔다).
    """
    out = list(raw_rows)
    applied = 0
    for p in proposal:
        key = (_norm(p["지자체"]), _norm(p["조례명"]))
        idx = [i for i, r in enumerate(out) if (_norm(r["지자체"]), _norm(r["조례명"])) == key and is_inspection_row(r)]
        if idx:
            out[idx[0]] = {k: p[k] for k in ("지자체", "조례명", "시행일", "조문")}
        else:
            out.append({k: p[k] for k in ("지자체", "조례명", "시행일", "조문")})
        applied += 1
    return out, applied
