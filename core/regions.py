"""법정동코드 (data/ref/의 법정동코드 전체자료).

- 법정동코드 10자리 = sigunguCd(앞 5) + bjdongCd(뒤 5).
- bjdongCd = 읍면동 3자리 + 리 2자리.
- 화면·조회에는 '존재' 코드만 쓴다. 조례 지역 매핑 리포트에서만 '폐지' 코드를 참고한다.
- 일반구가 있는 시(수원시 등)는 시 코드(41110)를 목록에서 빼고 구 코드(41111 …)만 쓴다.
  건축물대장 sigunguCd가 구 단위이기 때문이다.

core는 streamlit을 import하지 않는다. 캐시는 functools.lru_cache.
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

REF_DIR = Path(__file__).resolve().parents[1] / "data" / "ref"

# 같은 이름의 줄임말만 정규화한다. 개편·통합(예: 광주광역시 → 전남광주통합특별시)은 추측하지 않는다.
SIDO_ALIASES = {
    "서울": "서울특별시",
    "서울시": "서울특별시",
    "부산": "부산광역시",
    "부산시": "부산광역시",
    "대구": "대구광역시",
    "대구시": "대구광역시",
    "인천": "인천광역시",
    "인천시": "인천광역시",
    "대전": "대전광역시",
    "대전시": "대전광역시",
    "울산": "울산광역시",
    "울산시": "울산광역시",
    "세종": "세종특별자치시",
    "세종시": "세종특별자치시",
    "경기": "경기도",
    "충북": "충청북도",
    "충남": "충청남도",
    "경북": "경상북도",
    "경남": "경상남도",
    "제주": "제주특별자치도",
    "제주도": "제주특별자치도",
    "강원": "강원특별자치도",
    "전북": "전북특별자치도",
}

# 공고문에 흔한 옛 이름·줄임말(조례 매핑용 SIDO_ALIASES와 따로 둔다: 공고 지역 해석에만 쓴다)
NOTICE_SIDO_ALIASES = {
    "강원도": "강원특별자치도",
    "전라북도": "전북특별자치도",
    "광주": "전남광주통합특별시",
    "광주광역시": "전남광주통합특별시",
    "전남": "전남광주통합특별시",
    "전라남도": "전남광주통합특별시",
    "제주시": "제주특별자치도 제주시",
}


@dataclass(frozen=True)
class CodeRow:
    code: str  # 10자리
    name: str  # 공백 정리된 전체 이름 (예: "서울특별시 종로구 청운동")
    alive: bool  # 폐지여부 == "존재"

    @property
    def sigungu_cd(self) -> str:
        return self.code[:5]

    @property
    def bjdong_cd(self) -> str:
        return self.code[5:]


class RegionDataError(RuntimeError):
    """법정동코드 파일을 찾거나 읽지 못했다."""


def _ref_file() -> Path:
    files = sorted(REF_DIR.glob("bjdong_codes_*.csv")) + sorted(REF_DIR.glob("*법정동코드*.txt"))
    if not files:
        raise RegionDataError(f"{REF_DIR}에 법정동코드 파일(bjdong_codes_*.csv)이 없습니다.")
    return files[-1]  # 파일명 날짜가 가장 늦은 것


def _decode(raw: bytes) -> str:
    for enc in ("utf-8-sig", "cp949"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    raise RegionDataError("법정동코드 파일 인코딩을 알 수 없습니다(utf-8, cp949 아님).")


def _clean(name: str) -> str:
    return re.sub(r"\s+", " ", name).strip()


@lru_cache(maxsize=1)
def _all_rows() -> tuple[CodeRow, ...]:
    path = _ref_file()
    text = _decode(path.read_bytes())
    first = text.splitlines()[0]
    delim = "\t" if "\t" in first else ","
    reader = csv.reader(io.StringIO(text), delimiter=delim)
    header = [h.strip() for h in next(reader)]
    try:
        i_code, i_name, i_state = header.index("법정동코드"), header.index("법정동명"), header.index("폐지여부")
    except ValueError as e:
        raise RegionDataError(f"법정동코드 파일 컬럼이 예상과 다릅니다: {header}") from e
    out = []
    for r in reader:
        if len(r) <= max(i_code, i_name, i_state):
            continue
        code = r[i_code].strip()
        if len(code) != 10 or not code.isdigit():
            continue
        out.append(CodeRow(code, _clean(r[i_name]), r[i_state].strip() == "존재"))
    return tuple(out)


def _is_sido_level(c: CodeRow) -> bool:
    return c.code[2:] == "00000000"


def _is_sigungu_level(c: CodeRow) -> bool:
    return c.bjdong_cd == "00000" and not _is_sido_level(c)


@lru_cache(maxsize=2)
def _sigungu_rows(alive_only: bool = True) -> tuple[CodeRow, ...]:
    """대장 조회 단위의 시군구(일반구가 있는 시는 구). 코드 순."""
    rows = [c for c in _all_rows() if _is_sigungu_level(c) and (c.alive or not alive_only)]
    names = {c.name for c in rows}
    # 이름이 다른 시군구 이름의 접두어 + 공백이면 일반구를 거느린 시 → 제외
    parents = {n for n in names if any(o != n and o.startswith(n + " ") for o in names)}
    return tuple(c for c in rows if c.name not in parents)


@lru_cache(maxsize=1)
def parent_city_children() -> dict[str, tuple[str, ...]]:
    """일반구를 둔 시 이름 → 구 sigunguCd 목록. 예: '경기도 수원시' → ('41111', …)."""
    rows = [c for c in _all_rows() if _is_sigungu_level(c) and c.alive]
    names = {c.name for c in rows}
    out: dict[str, list[str]] = {}
    for n in names:
        kids = sorted(c.sigungu_cd for c in rows if c.name.startswith(n + " "))
        if kids:
            out[n] = kids
    return {k: tuple(v) for k, v in out.items()}


def normalize_sido(name: str) -> str:
    n = _clean(name)
    return SIDO_ALIASES.get(n, n)


def sido_of(name: str) -> str:
    return name.split(" ", 1)[0]


@lru_cache(maxsize=1)
def list_sido() -> list[str]:
    seen: dict[str, None] = {}
    for c in _sigungu_rows():
        seen.setdefault(sido_of(c.name), None)
    return list(seen)


@lru_cache(maxsize=64)
def list_sigungu(sido: str) -> list[tuple[str, str]]:
    """[(sigunguCd, 표시이름)]. 표시이름은 시도를 뺀 이름(세종은 '세종특별자치시')."""
    sido = normalize_sido(sido)
    out = []
    for c in _sigungu_rows():
        if sido_of(c.name) != sido:
            continue
        display = c.name[len(sido):].strip() or c.name
        out.append((c.sigungu_cd, display))
    return out


@lru_cache(maxsize=512)
def list_bjdong(sigungu_cd: str) -> list[tuple[str, str]]:
    """[(bjdongCd, 표시이름)].

    하위 리가 있는 읍·면은 목록에서 빼고 리를 '○○면 ○○리'로 보인다. 리가 없는 동은 그대로.
    """
    rows = [c for c in _all_rows() if c.alive and c.sigungu_cd == sigungu_cd and c.bjdong_cd != "00000"]
    sgg_name = next((c.name for c in _all_rows() if c.code == sigungu_cd + "00000"), "")
    by_emd: dict[str, list[CodeRow]] = {}
    for c in rows:
        by_emd.setdefault(c.bjdong_cd[:3], []).append(c)
    out = []
    for emd in sorted(by_emd):
        group = by_emd[emd]
        ri = [c for c in group if c.bjdong_cd[3:] != "00"]
        for c in sorted(ri or group, key=lambda x: x.code):
            display = c.name[len(sgg_name):].strip() if sgg_name and c.name.startswith(sgg_name) else c.name
            out.append((c.bjdong_cd, display))
    return out


def name_of(code: str) -> str | None:
    """5자리 시군구코드, 10자리 법정동코드 → 이름. '폐지' 코드도 이름은 돌려준다."""
    code = code.strip()
    if len(code) == 5:
        code = code + "00000"
    for c in _all_rows():
        if c.code == code:
            return c.name
    return None


def find_code(full_name: str) -> str | None:
    """'서울특별시 종로구 청운동' → '1111010100' (존재 코드만)."""
    target = _clean(full_name)
    for c in _all_rows():
        if c.alive and c.name == target:
            return c.code
    return None


def match_sigungu(sido: str, sigungu: str) -> dict:
    """조례의 시도·시군구 이름 → 대장 조회용 sigunguCd 목록.

    반환: {"codes": [...], "kind": "exact|parent_city|sido_only|abolished|none", "abolished": [...]}
    - parent_city: 일반구를 둔 시 → 구 코드 N개
    - sido_only: 시군구 이름이 없는 단일 자치단체(세종, 제주는 시 2개)
    - abolished: 이름은 맞지만 '폐지' 코드만 있음 → 사람이 매핑해야 함
    추측 매핑은 하지 않는다.
    """
    sido = normalize_sido(sido)
    sigungu = _clean(sigungu)
    full = f"{sido} {sigungu}".strip()
    alive = {c.name: c for c in _sigungu_rows()}
    if not sigungu:
        codes = [c.sigungu_cd for c in _sigungu_rows() if sido_of(c.name) == sido]
        return {"codes": codes, "kind": "sido_only" if codes else "none", "abolished": []}
    if full in alive:
        return {"codes": [alive[full].sigungu_cd], "kind": "exact", "abolished": []}
    kids = parent_city_children().get(full)
    if kids:
        return {"codes": list(kids), "kind": "parent_city", "abolished": []}
    dead = [c.sigungu_cd for c in _all_rows() if _is_sigungu_level(c) and not c.alive and c.name == full]
    return {"codes": [], "kind": "abolished" if dead else "none", "abolished": dead}


def resolve_local_gov(text: str | None) -> dict:
    """공고문의 지자체 표현 → 대장 조회용 sigunguCd 목록.

    예: '수원시'·'경기도 수원시청' → 수원시 4개 구, '대전광역시 중구청' → 대전 중구, '광주 서구' → 광주 서구,
    '서울특별시' → 서울 25개 구. 같은 이름이 여러 시도에 있으면(예: '중구') 고르지 않고 candidates로 돌려준다.
    반환: {"codes": [...], "kind": exact|parent_city|sido_only|ambiguous|none, "label": 표시이름, "candidates": [(이름, [codes])]}
    """
    empty = {"codes": [], "kind": "none", "label": "", "candidates": []}
    if not text or not text.strip():
        return empty
    t = _clean(re.sub(r"[()（）]", " ", text))
    # '중구청', '수원시청', '청주시청' → 청 떼기(단 '청'으로 끝나는 지명은 없다고 본다)
    tokens = [re.sub(r"(?<=[시군구])청$", "", w) for w in t.split(" ") if w]
    tokens = [w for w in tokens if w not in ("시청", "구청", "군청")]
    if not tokens:
        return empty
    sidos = set(list_sido())

    def as_sido(w: str) -> str | None:
        n = NOTICE_SIDO_ALIASES.get(w) or SIDO_ALIASES.get(w) or w
        return n if n in sidos else None

    sido = as_sido(tokens[0])
    rest = " ".join(tokens[1:]) if sido else " ".join(tokens)
    if sido and not rest:
        m = match_sigungu(sido, "")
        return {**m, "label": sido, "candidates": []}
    if sido:
        m = match_sigungu(sido, rest)
        if m["codes"]:
            return {**m, "label": f"{sido} {rest}", "candidates": []}
    # 시도 없이 시군구 이름만: 모든 시도에서 찾는다
    alias = NOTICE_SIDO_ALIASES.get(rest)
    if alias and " " in alias:  # '제주시' 같은 특수 이름
        sido_, sg = alias.split(" ", 1)
        return {**match_sigungu(sido_, sg), "label": alias, "candidates": []}
    pool = [s for s in sidos if not sido or s == sido]
    found: list[tuple[str, list[str]]] = []
    for s in pool:
        m = match_sigungu(s, rest)
        if m["codes"]:
            found.append((f"{s} {rest}", m["codes"]))
    if len(found) == 1:
        label, codes = found[0]
        return {"codes": codes, "kind": "parent_city" if len(codes) > 1 else "exact", "label": label, "candidates": []}
    if len(found) > 1:
        return {"codes": [], "kind": "ambiguous", "label": rest, "candidates": found}
    return {**empty, "label": t}


# ---------------------------------------------------------------- 도 → 시·군 → 구·군 → 동 선택

def _metro(sido: str) -> bool:
    """군을 구와 같은 단계에 두는 광역 단위(서울·광역시·세종). 시·군을 거느린 통합특별시는 도처럼 본다."""
    return sido.endswith("광역시") or sido in ("서울특별시", "세종특별자치시")


def split_sigungu(sido: str, name: str) -> tuple[str, str]:
    """시군구 표시이름을 (시·군, 구·군) 두 단계로 나눈다. 해당 없는 단계는 ''.

    '수원시 장안구' → ('수원시', '장안구'), '가평군' → ('가평군', ''), 서울 '종로구' → ('', '종로구'),
    대구 '달성군'(광역시의 군) → ('', '달성군'), 세종 → ('', '').
    """
    if " " in name:
        city, gu = name.split(" ", 1)
        return city, gu
    if name == sido:
        return "", ""
    if name.endswith("구") or (_metro(sido) and name.endswith("군")):
        return "", name
    return name, ""


@lru_cache(maxsize=64)
def sigungu_tree(sido: str) -> dict[str, list[tuple[str, str]]]:
    """{시·군: [(sigunguCd, 구·군)]}. 시·군 단계가 없는 자치구·광역시 군은 '' 아래에 둔다."""
    tree: dict[str, list[tuple[str, str]]] = {}
    for code, name in list_sigungu(sido):
        city, gu = split_sigungu(sido, name)
        tree.setdefault(city, []).append((code, gu))
    return tree


@lru_cache(maxsize=1)
def _locations() -> dict[str, tuple[str, str, str]]:
    out = {}
    for sido in list_sido():
        for city, items in sigungu_tree(sido).items():
            for code, gu in items:
                out[code] = (sido, city, gu)
    return out


def locate(sigungu_cd: str) -> tuple[str, str, str] | None:
    """sigunguCd → (시·도, 시·군, 구·군). 화면 목록에 없는 코드(폐지 등)는 None."""
    return _locations().get(sigungu_cd)


@dataclass(frozen=True)
class RegionHit:
    label: str  # '서울특별시 종로구 청운동'
    sigungu_cd: str
    bjdong_cd: str | None = None  # 동을 찾았으면 그 동


@lru_cache(maxsize=1)
def _search_rows() -> tuple[RegionHit, ...]:
    rows: list[RegionHit] = []
    for sido in list_sido():
        for code, name in list_sigungu(sido):
            base = name if name == sido else f"{sido} {name}"
            rows.append(RegionHit(base, code))
            rows += [RegionHit(f"{base} {dn}", code, bj) for bj, dn in list_bjdong(code)]
    return tuple(rows)


def search(query: str, limit: int = 30) -> list[RegionHit]:
    """지역 이름 검색. 띄어 쓴 낱말이 모두 들어 있는 시군구·동(예: '수원 장안', '청운동', '대전 중구').

    시군구가 동보다 앞, 낱말이 이름 끝과 꼭 맞을수록 앞.
    """
    words = [w for w in re.split(r"\s+", (query or "").strip()) if w]
    if not words:
        return []
    hits = [h for h in _search_rows() if all(w in h.label for w in words)]
    last = words[-1]

    def rank(h: RegionHit) -> tuple:
        tail = h.label.rsplit(" ", 1)[-1]
        return (h.bjdong_cd is not None, not (tail == last or tail.startswith(last)), len(h.label))

    return sorted(hits, key=rank)[:limit]
