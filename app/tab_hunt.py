"""탭1 맨 위: 이 지역 공고 찾기(단계 7-1).

검수된 공고 → 네이버 검색 후보 → 없으면 조례 기준 + 수동 업로드 안내.
후보는 링크 목록으로만 보여 주고, 사용자가 고른 링크만 본문을 가져와 분류·추출한다(결과는 미검수 → 아래 편집기로).
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from app.state import Ctx
from core import notice_hunter as nh
from core.conditions import BUSINESS_TYPE_LABEL
from core.llm import factory
from core.llm.base import LLMError

KIND = {"news": "뉴스", "web": "웹문서"}


def render(ctx: Ctx) -> None:
    st.subheader("이 지역 공고 찾기")
    st.caption(f"{ctx.region_label} · 검수된 공고 → 네이버 검색(뉴스·웹문서) 순서로 찾습니다. 첨부파일은 링크만 보여 드립니다.")
    if st.button("공고 찾기"):
        with st.spinner("찾는 중"):
            try:
                res = nh.hunt(ctx.sigungu_cd, ctx.region_label, ctx.eval_date, ctx.ordinance is not None)
            except nh.HunterError as e:
                st.error(str(e))
                return
        st.session_state["hunt"] = (ctx.sigungu_cd, res)

    saved = st.session_state.get("hunt")
    if not saved or saved[0] != ctx.sigungu_cd:
        return
    res: nh.HuntResult = saved[1]
    (st.success if res.stage != "none" else st.info)(res.message + (f" (검색 호출 {res.calls}회)" if res.calls else ""))
    if res.stage == "reviewed":
        for n in res.notices:
            st.markdown(f"- {n.program_name or n.notice_id} · 접수 {n.apply_start or '?'}~{n.apply_end or '?'}")
        st.caption("사이드바 '공고'에서 고를 수 있습니다.")
        return
    if res.stage != "search":
        return

    table = pd.DataFrame(
        [{"날짜": c.date, "구분": KIND[c.kind], "제목": c.title, "출처": c.source} for c in res.candidates]
    )
    ev = st.dataframe(table, hide_index=True, use_container_width=True, on_select="rerun", selection_mode="single-row", key="hunt-table")
    sel = ev.selection.rows if ev and ev.selection else []
    if not sel:
        st.caption("후보를 하나 고르면 본문을 가져와 추출할 수 있습니다.")
        return
    cand = res.candidates[sel[0]]
    st.markdown(f"[원문 열기]({cand.url})  ·  {cand.snippet}")
    if cand.source_type in ("NEWS", "PRESS_RELEASE"):
        st.warning("뉴스·보도자료입니다. 추출 결과는 원문 공고를 확인한 뒤에만 쓰세요.")
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
        st.session_state["draft"] = {
            "notice": r.notice,
            "issues": r.issues,
            "classify": {"evidence": c.evidence, "reason": c.reason, "repair": c.has_repair_section},
            "provider": f"{provider.name}:{provider.model} · 웹 {cand.source}",
            "usage": (r.usage.input_tokens + c.usage.input_tokens, r.usage.output_tokens + c.usage.output_tokens) if r.usage else None,
        }
        st.info("추출 결과를 아래 편집기에 열었습니다. 원문과 대조해 검수한 뒤 저장하세요.")
