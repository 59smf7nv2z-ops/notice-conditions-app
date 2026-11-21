"""지역 선택: 이름 검색 + 도 → 시·군 → 구·군 → 읍·면·동(여러 개).

처음 화면과 사이드바가 같은 선택을 쓴다. 선택은 session_state['region'] 한 곳에만 두고(v: 바뀔 때마다 +1),
화면마다 다른 위젯 키(prefix)는 자기가 본 v가 다르면 그 값으로 다시 채운다.
공고 지역 적용·검색 결과 고르기는 select()로 바꾼다(위젯 키를 직접 건드리지 않는다).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import streamlit as st

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


def _pick_hit(prefix: str, hits: list[regions.RegionHit]) -> None:
    i = st.session_state.get(f"{prefix}-hit")
    if i is None or i >= len(hits):
        return
    h = hits[i]
    s = state()
    if h.bjdong_cd:  # 같은 구에서 동을 이어 찾으면 쌓는다(여러 동 고르기)
        keep = s["dongs"] if s["sgg"] == h.sigungu_cd and not s["all"] else []
        select(h.sigungu_cd, False, list(dict.fromkeys(keep + [h.bjdong_cd])))
    else:
        select(h.sigungu_cd, False, [])
    st.session_state[f"{prefix}-q"] = ""
    st.session_state[f"{prefix}-hit"] = None


def _valid(key: str, options: list, fallback=None) -> None:
    if st.session_state.get(key) not in options:
        st.session_state[key] = fallback


def render(box, prefix: str, search: bool = True) -> Region:
    """box: st 또는 st.sidebar 같은 컨테이너."""
    s = state()
    ss = st.session_state
    if ss.get(f"{prefix}-v") != s["v"] or f"{prefix}-sido" not in ss:
        _push(prefix, s)
    marked = set(ss.get("notice_region_codes") or [])

    if search:
        q = box.text_input("지역 이름으로 찾기", key=f"{prefix}-q", placeholder="예: 청운동, 수원 장안구, 대전 중구")
        if q.strip():
            hits = regions.search(q)
            if hits:
                box.selectbox(
                    f"찾은 지역 {len(hits)}곳" + (" (앞 30곳)" if len(hits) >= 30 else ""), range(len(hits)), index=None,
                    format_func=lambda i: hits[i].label + ("  · 동" if hits[i].bjdong_cd else ""),
                    placeholder="골라 주세요", key=f"{prefix}-hit", on_change=_pick_hit, args=(prefix, hits),
                )
            else:
                box.caption("맞는 지역이 없습니다. 띄어쓰기로 나눠 보세요(예: '수원 장안').")

    sidos = regions.list_sido()
    _valid(f"{prefix}-sido", sidos)
    sido = box.selectbox("도·특별시·광역시", sidos, key=f"{prefix}-sido", index=None, placeholder="골라 주세요")

    tree = regions.sigungu_tree(sido) if sido else {}
    cities = list(tree)
    if cities == [""]:
        _valid(f"{prefix}-city", cities, "")
    else:
        _valid(f"{prefix}-city", cities)
    has_city = sido is not None and cities != [""]

    def city_fmt(c: str) -> str:
        if c == "":
            return "— 자치구·군 바로 고르기" if has_city else NA
        codes = {code for code, _ in tree.get(c, [])}
        return f"{c} · 공고 지역" if codes & marked else c

    city = box.selectbox(
        "시·군", cities, key=f"{prefix}-city", index=None, format_func=city_fmt,
        placeholder="골라 주세요" if sido else "도를 먼저 고르세요", disabled=not has_city,
    )

    items = tree.get(city, []) if city is not None else []
    gus = [g for _, g in items]
    code_of = {g: c for c, g in items}
    if gus == [""]:
        _valid(f"{prefix}-gu", gus, "")
    else:
        _valid(f"{prefix}-gu", gus)
    has_gu = bool(gus) and gus != [""]
    gu = box.selectbox(
        "구·군", gus, key=f"{prefix}-gu", index=None,
        format_func=lambda g: (f"{g} · 공고 지역" if code_of.get(g) in marked else g) if g else NA,
        placeholder="골라 주세요" if items else "시·군을 먼저 고르세요", disabled=not has_gu,
    )
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
    else:
        box.multiselect("읍·면·동(여러 개)", [], disabled=True, placeholder="구·군을 먼저 고르세요", key=f"{prefix}-dongs-none")

    if (sgg, all_sel, list(dongs)) != (s["sgg"], s["all"], list(s["dongs"])):
        select(sgg, all_sel, dongs)
        ss[f"{prefix}-v"] = state()["v"]
    return _region(sgg, all_sel, dongs)
