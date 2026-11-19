"""공고 찾기(단계 1): 지역을 고르면 네이버 검색 → 올해 공고로 보이는 글이 있으면 바로 분류·추출.

- auto_run: 화면 맨 위. 시군구마다 세션에서 한 번만 찾는다(검색 3회 + LLM 최대 1회). 사이드바에서 끌 수 있다.
  추출되면 초안(미검수)을 사이드바 '공고'에 넣고 공고 지역(법정동 전체)을 검색 필터에 적용한다.
- render: '① 공고문 분석'의 후보 목록. 인터넷 주소를 보여 주고, 다른 글을 골라 다시 추출할 수 있다.
- 검수된 공고(접수 마감 전)가 있으면 검색하지 않는다. 첨부파일(HWP·PDF)은 링크만 보여 준다.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from app import sidebar
from app.state import Ctx
from core import notice_hunter as nh
from core.conditions import BUSINESS_TYPE_LABEL
from core.llm import factory
from core.llm.base import LLMError, usage_summary

KIND = {"news": "뉴스", "web": "웹문서"}
AUTO_KEY = "auto-hunt"


def _hunts() -> dict:
    return st.session_state.setdefault("hunts", {})  # sigunguCd → HuntResult


def _set_draft(ctx: Ctx, cand: nh.Candidate, c, r, provider_name: str) -> str:
    """추출 결과를 초안으로 열고, 공고 지역을 필터에 적용·사이드바 공고로 고른다. 반환: 지역 안내문."""
    n = r.notice
    region = ""
    if ctx.sigungu_cd in n.sigungu_codes or not n.sigungu_codes:
        region = sidebar.apply_region(n.sigungu_codes or [ctx.sigungu_cd], n.local_gov or "", current=ctx.sigungu_cd)
        st.session_state["pending_notice"] = (list(n.sigungu_codes or [ctx.sigungu_cd]), n.notice_id)  # 사이드바 '공고'에서 이 초안을 고른 상태로
    st.session_state["draft"] = {
        "region": region,
        "notice": n,
        "issues": r.issues,
        "classify": {"evidence": c.evidence, "confidence": c.confidence, "repair": c.has_repair_section},
        "provider": f"{provider_name}:{c.usage.model} · 웹 {cand.source}",
        "usage": usage_summary([c.usage]),
    }
    return region


def auto_run(ctx: Ctx) -> None:
    on = st.sidebar.toggle("지역을 고르면 공고 자동 검색·추출", True, key=AUTO_KEY,
                           help="네이버 검색 3회, 올해 공고로 보이는 글이 있으면 LLM 추출 1회. 시군구마다 한 번만.")
    hunts = _hunts()
    if on and ctx.sigungu_cd not in hunts:
        stt = factory.status("extract")
        provider = None if stt.is_mock else factory.get_provider("extract")  # 샘플 모드에선 검색만(샘플 조건이 실제처럼 보이지 않게)
        with st.spinner(f"{ctx.region_label} 공고 찾는 중" + ("" if provider is None else " · 찾으면 바로 조건 추출")):
            try:
                res = nh.hunt(ctx.sigungu_cd, ctx.region_label, ctx.eval_date, ctx.ordinance is not None, auto_provider=provider)
            except nh.HunterError as e:
                res = nh.HuntResult("none", message=str(e))
        hunts[ctx.sigungu_cd] = res
        a = res.auto
        if a and a.extract is not None and not a.region_mismatch:
            for code in a.extract.notice.sigungu_codes:  # 같은 공고 지역(수원시 4개 구 등)은 다시 찾지 않는다
                hunts.setdefault(code, res)
            _set_draft(ctx, a.candidate, a.classify, a.extract, getattr(provider, "name", "mock"))
            st.rerun()
    res = hunts.get(ctx.sigungu_cd)
    if res is not None:
        summary(ctx, res)


def summary(ctx: Ctx, res: nh.HuntResult) -> None:
    """화면 맨 위 한두 줄: 찾은 공고·인터넷 주소·자동 추출 결과."""
    a = res.auto
    if res.stage == "reviewed":
        st.success(f"공고: {ctx.region_label}의 {res.message} 사이드바 '공고'에서 고르세요.")
        return
    if a and a.extract is not None:
        n = a.extract.notice
        head = f"공고를 찾아 조건을 추출했습니다: [{a.candidate.title}]({a.candidate.url}) · {a.candidate.source}"
        if a.region_mismatch:
            st.warning(f"{head}  \n추출한 지자체({n.local_gov or '?'})가 고른 지역과 달라 필터에 적용하지 않았습니다. '① 공고문 분석'에서 다른 글을 고르세요.")
            return
        state, msg = n.period_status(ctx.eval_date)
        body = f"{head}  \n{'접수 중 · ' if state == 'OPEN' else '⚠️ '}{msg}  \n'① 공고문 분석'에서 원문 근거와 대조해 검수·수정하세요(지금은 미검수 초안으로 판정)."
        (st.success if state == "OPEN" else st.warning)(body)
        return
    if a and a.classify is not None:
        st.info(f"찾은 글 [{a.candidate.title}]({a.candidate.url})은 '{BUSINESS_TYPE_LABEL[a.classify.business_type]}'로 분류되어 조건을 추출하지 않았습니다. '① 공고문 분석'에서 다른 글을 고를 수 있습니다.")
        return
    if a and a.error:
        st.error(f"공고 자동 추출 실패: {a.error}")
        return
    extra = ""
    if a and a.skipped:
        extra = f" 상위 글 {len(a.skipped)}건은 본문을 가져오지 못했습니다(로봇 차단·첨부파일 등)."
    if res.stage == "search":
        st.info(f"공고 검색: {res.message}{extra} '① 공고문 분석'에서 후보와 인터넷 주소를 볼 수 있습니다.")
    else:
        st.info(f"공고 검색: {res.message}")


def render(ctx: Ctx) -> None:
    st.subheader("이 지역 공고 찾기")
    st.caption(f"{ctx.region_label} · 검수된 공고 → 네이버 검색(구청 게시판 웹문서·뉴스) 순서로 찾습니다. 첨부파일은 링크만 보여 드립니다.")
    if st.button("다시 찾기" if ctx.sigungu_cd in _hunts() else "공고 찾기"):
        with st.spinner("찾는 중"):
            try:
                res = nh.hunt(ctx.sigungu_cd, ctx.region_label, ctx.eval_date, ctx.ordinance is not None)
            except nh.HunterError as e:
                st.error(str(e))
                return
        _hunts()[ctx.sigungu_cd] = res

    res: nh.HuntResult | None = _hunts().get(ctx.sigungu_cd)
    if res is None:
        return
    (st.success if res.stage != "none" else st.info)(res.message + (f" (검색 호출 {res.calls}회)" if res.calls else ""))
    if res.stage == "reviewed":
        for n in res.notices:
            link = f" · [원문]({n.source_url})" if n.source_url else ""
            st.markdown(f"- {n.program_name or n.notice_id} · 접수 {n.apply_start or '?'}~{n.apply_end or '?'}{link}")
        st.caption("사이드바 '공고'에서 고를 수 있습니다.")
        return
    if res.stage != "search":
        return
    a = res.auto
    if a:
        for url, why in a.skipped:
            st.caption(f"자동 추출 건너뜀: {url} — {why}")
        if a.page and a.page.attachments:
            st.markdown("**자동 추출한 글의 첨부파일**(공고문 원본이면 내려받아 아래 업로드에 넣으세요)")
            for label_, url in a.page.attachments[:20]:
                st.markdown(f"- [{label_}]({url})")

    table = pd.DataFrame([
        {"관련도": c.score, "연도": c.year or "", "구분": KIND[c.kind], "제목": c.title, "출처": c.source, "주소": c.url}
        for c in res.candidates
    ])
    ev = st.dataframe(
        table, hide_index=True, use_container_width=True, on_select="rerun", selection_mode="single-row", key="hunt-table",
        column_config={"주소": st.column_config.LinkColumn("인터넷 주소", display_text="열기"), "관련도": st.column_config.NumberColumn(width="small")},
    )
    sel = ev.selection.rows if ev and ev.selection else []
    if not sel:
        st.caption("후보를 하나 고르면 본문을 가져와 추출할 수 있습니다. 관련도: 올해 글·구청 사이트·신청 안내일수록 높음.")
        return
    cand = res.candidates[sel[0]]
    st.markdown(f"**인터넷 주소** {cand.url}  \n{cand.snippet}")
    if cand.source_type in ("NEWS", "PRESS_RELEASE"):
        st.warning("뉴스·보도자료입니다. 추출 결과는 원문 공고를 확인한 뒤에만 쓰세요.")
    if nh.is_file_link(cand):
        st.info("첨부파일 링크입니다. 내려받아 아래 '공고 파일 올려 조건 추출'에 넣으세요.")
        return
    stt = factory.status("extract")
    label = "샘플 결과(외부 전송 없음)" if stt.is_mock else f"{stt.label}로 본문 전송"
    if st.button(f"선택한 링크 본문 가져와 추출 · {label}"):
        provider = factory.get_provider("extract")
        try:
            with st.spinner("본문 가져오는 중"):
                page, c, r = nh.extract_from_candidate(cand, provider)
        except (nh.HunterError, LLMError) as e:
            st.error(str(e))
            return
        if page.attachments:
            st.markdown("**첨부파일**(내려받아 아래 업로드에 넣으세요)")
            for label_, url in page.attachments[:20]:
                st.markdown(f"- [{label_}]({url})")
        if r is None:
            st.warning(f"이 글은 '{BUSINESS_TYPE_LABEL[c.business_type]}'로 분류되어 조건을 추출하지 않습니다. 근거: {c.evidence or '-'}")
            return
        _set_draft(ctx, cand, c, r, provider.name)
        st.info("추출 결과를 아래 편집기에 열었습니다. 원문과 대조해 검수한 뒤 저장하세요.")
