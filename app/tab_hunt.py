"""공고 찾기: '검색'을 누르면 네이버 검색 → 올해 공고로 보이는 글 여러 건을 분류·추출해 한 조건으로 합친다.

- search: '검색' 버튼을 눌렀을 때만 찾는다(검색 3회 + 글마다 LLM 1회, 최대 3건). 지역을 고르기만 해서는 호출하지 않는다.
  합친 조건은 초안(미검수)으로 열고, 사이드바 '공고'에서 고른 상태로, 공고 지역(읍·면·동 전체)을 지역 선택에 적용한다.
- panel: 후보 목록(인터넷 주소). 여러 글에 체크해 '추출·합성'을 다시 할 수 있다. 같은 글은 LLM을 다시 부르지 않는다.
- 검수된 공고(접수 마감 전)가 있으면 검색하지 않는다. 첨부파일(HWP·PDF)은 링크만 보여 준다.
"""

from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

from app import sidebar
from core import notice_hunter as nh
from core.llm import factory
from core.llm.base import LLMError, usage_summary
from core.notice_merge import SOURCE_LABEL

KIND = {"news": "뉴스", "web": "웹문서"}
MAX_PICK = 6  # 한 번에 추출할 수 있는 글 수(글마다 LLM 1회)


def _hunts() -> dict:
    return st.session_state.setdefault("hunts", {})  # sigunguCd → HuntResult


def _cache() -> dict:
    return st.session_state.setdefault("extracted", {})  # 주소 → SourceResult (같은 글 LLM 재호출 방지)


def _set_draft(sgg: str, a: nh.AutoExtract, provider_name: str) -> str:
    """합친 조건을 초안으로 열고 지역 선택·사이드바 공고에 적용. 반환: 지역 안내문."""
    m = a.merged
    n = m.notice
    region = sidebar.apply_region(n.sigungu_codes or [sgg], n.local_gov or "", current=sgg)
    st.session_state["pending_notice"] = (list(n.sigungu_codes or [sgg]), n.notice_id)
    used = a.used
    st.session_state.pop("reviewed", None)  # 새 초안은 다시 검수해야 한다
    st.session_state["draft"] = {
        "region": region,
        "notice": n,
        "issues": m.issues,
        "classify": {
            "evidence": used[0].classify.evidence, "confidence": used[0].classify.confidence,
            "repair": any(r.classify.has_repair_section for r in used),
        },
        "provider": f"{provider_name}:{used[0].classify.usage.model} · 웹 글 {len(m.sources)}건",
        "usage": usage_summary(a.usages),
        "sources": [(i + 1, s.title, s.url, SOURCE_LABEL.get(s.notice.source_type, "글")) for i, s in enumerate(m.sources)],
    }
    return region


def search(sgg: str, label: str, eval_date: date, has_ordinance: bool) -> nh.HuntResult:
    """'검색' 버튼: 네이버 검색 → 올해 공고로 보이는 글 최대 3건을 추출해 합친다. 합치면 초안을 열고 다시 그린다."""
    hunts = _hunts()
    stt = factory.status("extract")
    provider = None if stt.is_mock else factory.get_provider("extract")  # 샘플 모드에선 검색만(샘플 조건이 실제처럼 보이지 않게)
    draft = st.session_state.get("draft") or {}
    if draft.get("origin") == "upload" and sgg in draft["notice"].sigungu_codes:
        provider = None  # 올린 공고문에서 뽑은 조건이 있으면 검색만 한다(덮어쓰지 않음)
    with st.spinner(f"{label} 공고 찾는 중" + ("" if provider is None else " · 찾으면 바로 조건 추출")):
        try:
            res = nh.hunt(sgg, label, eval_date, has_ordinance, auto_provider=provider, cache=_cache())
        except nh.HunterError as e:
            res = nh.HuntResult("none", message=str(e))
    hunts[sgg] = res
    a = res.auto
    if a and a.merged is not None:
        for code in a.merged.notice.sigungu_codes:  # 같은 공고 지역(수원시 4개 구 등)은 결과를 함께 쓴다
            hunts.setdefault(code, res)
        _set_draft(sgg, a, getattr(provider, "name", "mock"))
        st.rerun()
    return res


def result(sgg: str) -> nh.HuntResult | None:
    """이 시군구에서 '검색'을 누른 결과(없으면 None)."""
    return _hunts().get(sgg)


def summary(res: nh.HuntResult | None, eval_date: date, label: str) -> None:
    """화면 위 몇 줄: 찾은 공고·인터넷 주소·자동 추출 결과."""
    if res is None:
        return
    a = res.auto
    if res.stage == "reviewed":
        st.success(f"공고: {label}의 {res.message} 사이드바 '공고'에서 고르세요.")
        return
    if a and a.merged is not None:
        links = " · ".join(f"[{s.title[:40]}]({s.url})" for s in a.merged.sources)
        st.success(f"공고 글 {len(a.merged.sources)}건에서 조건을 뽑아 합쳤습니다: {links}")
        return
    if a and a.region_mismatch:
        st.warning("찾은 글이 모두 다른 지역 공고라 적용하지 않았습니다. 아래 '공고 검색 결과'에서 다른 글을 고르세요.")
        return
    if a and a.error:
        st.error(f"공고에서 조건을 뽑지 못했습니다({a.error}). 아래 '공고 검색 결과'에서 다른 글을 고르거나 공고문을 직접 올리세요.")
        return
    if a and a.sources:
        st.info("올해 글을 열어 봤지만 조건을 뽑을 수 있는 공고가 아니었습니다(" + "; ".join(r.reason for r in a.sources[:3]) + "). 아래 '공고 검색 결과'에서 다른 글을 고르세요.")
        return
    st.info(f"공고 검색: {res.message}")


def _status_lines(a: nh.AutoExtract) -> None:
    tags = {s.url: i + 1 for i, s in enumerate(a.merged.sources)} if a.merged else {}
    for r in a.sources:
        if r.status == "used" and r.candidate.url in tags:
            st.markdown(f"✓ [출처 {tags[r.candidate.url]}] [{r.candidate.title}]({r.candidate.url})")
        elif r.status == "used":
            st.markdown(f"– [{r.candidate.title}]({r.candidate.url}) · 회차가 달라 합치지 않음")
        else:
            st.markdown(f"✗ [{r.candidate.title}]({r.candidate.url}) · {r.reason}")


def panel(sgg: str, label: str, eval_date: date, has_ordinance: bool, prefix: str) -> None:
    """후보 목록과 여러 글 추출·합성."""
    hunts = _hunts()
    c1, c2 = st.columns([1, 3])
    if c1.button("다시 검색" if sgg in hunts else "공고 검색", key=f"{prefix}-hunt-btn", icon=":material/search:"):
        search(sgg, label, eval_date, has_ordinance)
    res: nh.HuntResult | None = hunts.get(sgg)
    if res is None:
        c2.caption("'공고 검색'을 누르면 네이버에서 이 지역 공고를 찾아 조건을 추출합니다.")
        return
    c2.caption(res.message + (f" (검색 호출 {res.calls}회)" if res.calls else ""))
    if res.stage == "reviewed":
        for n in res.notices:
            link = f" · [원문]({n.source_url})" if n.source_url else ""
            st.markdown(f"- {n.program_name or n.notice_id} · 접수 {n.apply_start or '?'}~{n.apply_end or '?'}{link}")
        return
    if res.stage != "search":
        return
    a = res.auto
    if a and a.sources:
        with st.expander(f"추출한 글 {len(a.sources)}건", expanded=a.merged is None):
            _status_lines(a)
            pages = [r for r in a.sources if r.page and r.page.attachments]
            for r in pages[:3]:
                st.caption(f"첨부파일 — {r.candidate.source}(공고문 원본이면 내려받아 직접 올리세요)")
                for label_, url in r.page.attachments[:10]:
                    st.markdown(f"- [{label_}]({url})")

    checked = {r.candidate.url for r in a.used} if a else set()
    table = pd.DataFrame([
        {"선택": c.url in checked, "관련도": c.score, "연도": c.year or "", "구분": KIND[c.kind], "제목": c.title,
         "출처": c.source, "주소": c.url}
        for c in res.candidates
    ])
    edited = st.data_editor(
        table, hide_index=True, use_container_width=True, key=f"{prefix}-cands-{sgg}-{len(checked)}-{hash(frozenset(checked))}",
        disabled=["관련도", "연도", "구분", "제목", "출처", "주소"],
        column_config={
            "선택": st.column_config.CheckboxColumn(width="small", help="여러 개 고르면 각각 추출해 한 조건으로 합칩니다"),
            "주소": st.column_config.LinkColumn("인터넷 주소", display_text="열기"),
            "관련도": st.column_config.NumberColumn(width="small"),
        },
    )
    picked = [res.candidates[i] for i in edited.index[edited["선택"]].tolist()]
    st.caption("관련도: 올해 글·구청 사이트·신청 안내일수록 높음. 여러 글을 고르면 최신 회차 글끼리 합치고, 공고 → 보도자료 → 뉴스 순으로 값을 씁니다.")
    if not picked:
        return
    if len(picked) > MAX_PICK:
        st.warning(f"한 번에 {MAX_PICK}건까지 추출합니다. 앞의 {MAX_PICK}건만 씁니다.")
        picked = picked[:MAX_PICK]
    stt = factory.status("extract")
    new = [c for c in picked if c.url not in _cache()]
    cost = "샘플 결과(외부 전송 없음)" if stt.is_mock else (f"{stt.label}로 본문 {len(new)}건 전송" if new else "이미 추출한 글")
    if st.button(f"고른 글 {len(picked)}건에서 조건 뽑아 합치기 · {cost}", type="primary", key=f"{prefix}-extract"):
        provider = factory.get_provider("extract")
        with st.spinner("본문 가져와 추출하는 중"):
            try:
                a2 = nh.extract_sources(picked, provider, sgg, max_sources=len(picked), max_tries=len(picked), cache=_cache())
            except LLMError as e:
                st.error(str(e))
                return
        res.auto = a2
        if a2.merged is None:
            st.warning("고른 글에서 조건을 뽑지 못했습니다.")
            _status_lines(a2)
            return
        _set_draft(sgg, a2, provider.name)
        st.rerun()
