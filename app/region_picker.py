"""지역 선택: 이름 검색 + 도 → 시·군 → 구·군 → 읍·면·동(여러 개).

처음 화면과 사이드바가 같은 선택을 쓴다. 선택은 session_state['region'] 한 곳에만 두고(v: 바뀔 때마다 +1),
화면마다 다른 위젯 키(prefix)는 자기가 본 v가 다르면 그 값으로 다시 채운다.
공고 지역 적용·검색 결과 고르기는 select()로 바꾼다(위젯 키를 직접 건드리지 않는다).
"""

from __future__ import annotations

from contextlib import nullcontext
from dataclasses import dataclass, field

import streamlit as st

from app import wheel_picker
from core import regions

KEY = "region"
NA = "해당 없음"


@dataclass
class Region:
    sido: str | None = None
    city: str = ""
    gu: str = ""
    sigungu_cd: str | None = None
    all_selected: bool = False
    bjdong_cds: list[str] = field(default_factory=list)
    bjdong_names: dict[str, str] = field(default_factory=dict)

    @property
    def ready(self) -> bool:
        return self.sigungu_cd is not None

    @property
    def sigungu_name(self) -> str:
        """list_sigungu 표시이름('수원시 장안구', '종로구', 세종은 '세종특별자치시')."""
        return " ".join(x for x in (self.city, self.gu) if x) or (self.sido or "")

    @property
    def label(self) -> str:
        return f"{self.sido} {self.sigungu_name}".replace(f"{self.sido} {self.sido}", self.sido or "") if self.sido else ""


def state() -> dict:
    return st.session_state.setdefault(KEY, {"sgg": None, "all": False, "dongs": [], "v": 0})


def select(sigungu_cd: str | None, all_dongs: bool = False, dongs: list[str] | None = None) -> None:
    """지역을 밖에서 정한다(공고 지역 적용·검색 결과). 다음에 그려지는 선택 위젯이 이 값으로 바뀐다."""
    s = state()
    s.update(sgg=sigungu_cd, all=all_dongs, dongs=list(dongs or []), v=s["v"] + 1)


def current() -> Region:
    """위젯을 그리지 않고 지금 선택을 읽는다."""
    s = state()
    return _region(s["sgg"], s["all"], s["dongs"])


def _region(sgg: str | None, all_dongs: bool, dongs: list[str]) -> Region:
    loc = regions.locate(sgg) if sgg else None
    if not loc:
        return Region()
    names = dict(regions.list_bjdong(sgg))
    cds = list(names) if all_dongs else [d for d in dongs if d in names]
    return Region(loc[0], loc[1], loc[2], sgg, all_dongs, cds, names)


def _push(prefix: str, s: dict) -> None:
    ss = st.session_state
    loc = regions.locate(s["sgg"]) if s["sgg"] else None
    ss[f"{prefix}-sido"] = loc[0] if loc else None
    ss[f"{prefix}-city"] = loc[1] if loc else None
    ss[f"{prefix}-gu"] = loc[2] if loc else None
    if loc:
        ss[f"{prefix}-all-{s['sgg']}"] = s["all"]
        ss[f"{prefix}-dongs-{s['sgg']}"] = list(s["dongs"])
    ss[f"{prefix}-v"] = s["v"]


def _apply_hit(prefix: str, h: regions.RegionHit) -> None:
    """검색 결과 하나를 지역 선택에 적용한다. 같은 구에서 동을 이어 찾으면 쌓는다(여러 동 고르기)."""
    s = state()
    if h.bjdong_cd:
        keep = s["dongs"] if s["sgg"] == h.sigungu_cd and not s["all"] else []
        select(h.sigungu_cd, False, list(dict.fromkeys(keep + [h.bjdong_cd])))
    else:
        select(h.sigungu_cd, False, [])
    st.session_state[f"{prefix}-clear-q"] = True


def _ctx(box):
    """st.sidebar·열은 with로 쓰고, st 모듈 자체는 그대로."""
    return nullcontext() if box is st else box


def _valid(key: str, options: list, fallback=None) -> None:
    if st.session_state.get(key) not in options:
        st.session_state[key] = fallback


def render(box, prefix: str, search: bool = True, row: bool = False) -> Region:
    """box: st 또는 st.sidebar 같은 컨테이너. 도 → 시·군 → 구·군을 휠로 고르고, 앞 단계를 고르면 다음 휠이 미끄러져 나온다.

    row=True면 휠을 나란히(처음 화면), 아니면 위아래로(사이드바). 휴대폰에서는 운영체제 기본 선택 창.
    """
    s = state()
    ss = st.session_state
    if ss.pop(f"{prefix}-clear-q", False):  # 검색 결과를 골랐으면 검색어를 비운다(입력칸을 그리기 전에만 바꿀 수 있다)
        ss[f"{prefix}-q"] = ""
    if ss.get(f"{prefix}-v") != s["v"] or f"{prefix}-sido" not in ss:
        _push(prefix, s)
    marked = set(ss.get("notice_region_codes") or [])
    rows = 5 if row else 3

    if search:
        q = box.text_input("지역 이름으로 찾기", key=f"{prefix}-q", placeholder="예: 청운동, 수원 장안구, 대전 중구")
        if q.strip():
            hits = regions.search(q)
            if hits:
                with _ctx(box):
                    i = wheel_picker.wheel(
                        f"찾은 지역 {len(hits)}곳" + (" (앞 30곳)" if len(hits) >= 30 else ""), range(len(hits)), None,
                        key=f"{prefix}-hit-wheel-{q.strip()}", rows=3, placeholder="골라 주세요",
                        format_func=lambda i: hits[i].label + ("  · 동" if hits[i].bjdong_cd else ""),
                    )
                if i is not wheel_picker.NOTHING and i is not None:
                    _apply_hit(prefix, hits[i])
                    st.rerun()
            else:
                box.caption("맞는 지역이 없습니다. 띄어쓰기로 나눠 보세요(예: '수원 장안').")

    slots = iter(box.columns(3, gap="small") if row else (box, box, box))

    def pick(label: str, k: str, options: list, fmt, first: bool = False):
        """휠 하나. 고른 값은 {prefix}-{k}에 둔다(검색·공고 지역 적용과 같은 자리)."""
        key = f"{prefix}-{k}"
        with _ctx(next(slots)):
            got = wheel_picker.wheel(label, options, ss.get(key), key=f"{key}-wheel", format_func=fmt,
                                     rows=rows, reveal=not first)
        if got is not wheel_picker.NOTHING:
            ss[key] = got
        return ss.get(key)

    sidos = regions.list_sido()
    _valid(f"{prefix}-sido", sidos)
    sido = pick("도·특별시·광역시", "sido", sidos, str, first=True)

    tree = regions.sigungu_tree(sido) if sido else {}
    cities = list(tree)
    if cities == [""]:
        _valid(f"{prefix}-city", cities, "")
    else:
        _valid(f"{prefix}-city", cities)
    has_city = sido is not None and cities != [""]

    def city_fmt(c: str) -> str:
        if c == "":
            return "— 자치구·군 바로 고르기"
        codes = {code for code, _ in tree.get(c, [])}
        return f"{c} · 공고 지역" if codes & marked else c

    # 도를 골라야 시·군 휠이 나온다. 광역시·특별시처럼 시·군 단계가 없으면 바로 구·군
    city = pick("시·군", "city", cities, city_fmt) if has_city else ss.get(f"{prefix}-city")

    items = tree.get(city, []) if city is not None else []
    gus = [g for _, g in items]
    code_of = {g: c for c, g in items}
    if gus == [""]:
        _valid(f"{prefix}-gu", gus, "")
    else:
        _valid(f"{prefix}-gu", gus)
    has_gu = bool(gus) and gus != [""]
    if has_gu:
        gu = pick("구·군", "gu", gus, lambda g: f"{g} · 공고 지역" if code_of.get(g) in marked else g)
    else:
        gu = ss.get(f"{prefix}-gu")
    sgg = code_of.get(gu) if gu is not None else None

    all_sel, dongs = False, []
    if sgg:
        names = dict(regions.list_bjdong(sgg))
        all_sel = box.checkbox(f"읍·면·동 전체 ({len(names)}곳)", key=f"{prefix}-all-{sgg}")
        if not all_sel:
            dk = f"{prefix}-dongs-{sgg}"
            if dk in ss:
                ss[dk] = [d for d in ss[dk] if d in names]
            dongs = box.multiselect(
                "읍·면·동(여러 개)", list(names), key=dk, format_func=names.get,
                placeholder="동을 고르세요(이름 입력해 찾기)",
            )

    if (sgg, all_sel, list(dongs)) != (s["sgg"], s["all"], list(s["dongs"])):
        select(sgg, all_sel, dongs)
        ss[f"{prefix}-v"] = state()["v"]
    return _region(sgg, all_sel, dongs)
