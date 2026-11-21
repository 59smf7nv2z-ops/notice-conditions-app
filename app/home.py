"""처음 화면: 지역 선택(도 → 시·군 → 구·군 → 읍·면·동, 이름 검색) | 공고문 직접 올리기.

지역(구·군)을 고르면 그 지역 조례(소규모 노후건축물 점검 대상 규모)를 보여 주고, 공고를 자동으로 찾아 조건을 추출·합성한다.
'후보 건물 찾기'를 누르면 작업 화면(② 지역 일괄 대조)으로 넘어간다.
"""

from __future__ import annotations

from datetime import date

import streamlit as st

from app import region_picker, tab_hunt, tab_upload
from core import ordinances
from core.ordinances import OrdinanceConditions

HERO = """
<div style="padding:28px 0 8px 0">
  <div style="font-size:0.95rem;color:#2e7d32;font-weight:600;letter-spacing:0.02em">구청 건축안전 실무용</div>
  <div style="font-size:2.3rem;font-weight:800;line-height:1.25;margin:6px 0 10px 0">소규모 노후건축물<br>안전점검 지원 대상 찾기</div>
  <div style="font-size:1.05rem;opacity:0.8;max-width:760px">
    지역을 고르면 그 지역 조례와 올해 공고를 찾아 지원 조건을 뽑고, 건축물대장에서 조건에 맞는 건물을 골라 드립니다.
    결과는 '자격 후보'이며 최종 선정은 담당자·위원회가 합니다.
  </div>
  <div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:16px;font-size:0.9rem">
    <span style="padding:4px 12px;border-radius:999px;background:rgba(46,125,50,0.12)">1 지역·공고 조건</span>
    <span style="opacity:0.5">→</span>
    <span style="padding:4px 12px;border-radius:999px;background:rgba(127,127,127,0.12)">2 후보 목록·지도</span>
    <span style="opacity:0.5">→</span>
    <span style="padding:4px 12px;border-radius:999px;background:rgba(127,127,127,0.12)">3 안내문</span>
  </div>
</div>
"""


def _go(section: str) -> None:
    st.session_state["stage"] = "work"
    st.session_state["section"] = section
    st.rerun()


def _bound(v, b: str, unit: str) -> str:
    return f"{v:g}{unit} {'이하' if b == 'LE' else '미만'}" if isinstance(v, float) else f"{v}{unit} {'이하' if b == 'LE' else '미만'}"


def ordinance_card(o: OrdinanceConditions | None) -> None:
    st.markdown("**지자체 조례 · 소규모 노후건축물 점검 대상**")
    if o is None:
        st.caption("이 지역 조례 자료가 없습니다. 공고가 없으면 법정 기준(사용승인 후 30년 이상)으로 판정합니다.")
        return
    sc = o.effective_scale()
    parts = [f"사용승인 후 {o.min_years}년 이상" if o.min_years else "연수는 조례가 따로 정함"]
    if sc["max_floors"] is not None:
        parts.append(_bound(sc["max_floors"], sc["floors_bound"], "층"))
    if sc["max_area"] is not None:
        parts.append("연면적 " + _bound(sc["max_area"], sc["area_bound"], "㎡"))
    if o.scale_rule_type in ("DISCRETION", "NONE"):
        parts.append("규모 수치 없음(단체장 재량)" if o.scale_rule_type == "DISCRETION" else "점검대상 조문 없음")
    elif o.scale_rule_type in ("STRUCTURE_RULE_REF", "CONSTRUCTION_ACT_REF") and sc["max_floors"] is None and sc["max_area"] is None:
        parts.append("규모는 다른 법령 기준 참조(수치 확인 필요)")
    if o.use_filter:
        parts.append("용도 " + ", ".join(o.use_filter))
    if o.structure_filter:
        parts.append("구조 " + ", ".join(o.structure_filter))
    st.markdown(" · ".join(parts))
    st.caption(f"{o.ordinance_name} ({o.effective_date or '시행일 미상'})" + (f" · {o.source_article}" if o.source_article else "")
               + (" · 분류 검토 필요" if o.review_needed else ""))


def draft_card(sgg: str | None) -> None:
    draft = st.session_state.get("draft")
    if not draft:
        return
    n = draft["notice"]
    if sgg and n.sigungu_codes and sgg not in n.sigungu_codes:
        return
    st.markdown(f"**추출한 공고 조건** · {n.program_name or n.notice_id} :orange-badge[미검수]")
    conds = []
    if n.min_years:
        conds.append(f"사용승인 후 {n.min_years}년 이상")
    elif n.built_before_year:
        conds.append(f"{n.built_before_year}년 이전 사용승인")
    if n.max_floors is not None:
        conds.append(_bound(n.max_floors, n.floors_bound, "층"))
    if n.max_area is not None:
        conds.append("연면적 " + _bound(n.max_area, n.area_bound, "㎡"))
    if n.use_filter:
        conds.append("용도 " + ", ".join(n.use_filter))
    if n.structure_filter:
        conds.append("구조 " + ", ".join(n.structure_filter))
    st.markdown(" · ".join(conds) or "판정 조건을 찾지 못했습니다(법정 기준 적용)")
    state, msg = n.period_status(date.today())
    (st.success if state == "OPEN" else st.warning)(("" if state == "OPEN" else "⚠️ ") + msg)
    if draft.get("region"):
        st.caption(draft["region"])
    if draft.get("issues"):
        st.caption(f"확인할 점 {len(draft['issues'])}건 · 원문 근거는 '조건 검수·수정'에서 볼 수 있습니다.")
    if st.button("조건 검수·수정하기", key="home-review"):
        _go("notice")


def render() -> None:
    st.markdown(HERO, unsafe_allow_html=True)
    left, right = st.columns([3, 2], gap="large")
    with left, st.container(border=True):
        st.markdown("#### 지역 선택")
        st.caption("도 → 시·군 → 구·군 → 읍·면·동 순서로 고르거나, 이름으로 찾으세요. 동은 여러 개 고를 수 있습니다.")
        reg = region_picker.render(st, "home")
        tab_hunt.auto_toggle(st, "home")
    with right, st.container(border=True):
        st.markdown("#### 공고문 직접 올리기")
        st.caption("HWP·HWPX·PDF·DOCX·XLSX·이미지. 여러 파일이면 한 공고로 묶어 추출합니다.")
        tab_upload.upload_box("home")

    if not reg.ready:
        draft_card(None)
        return

    o = ordinances.get_ordinance(reg.sigungu_cd)
    res = tab_hunt.ensure(reg.sigungu_cd, reg.label, date.today(), o is not None)

    st.markdown(f"#### {reg.label} · 조례와 공고")
    c1, c2 = st.columns([2, 3], gap="large")
    with c1, st.container(border=True):
        ordinance_card(o)
    with c2, st.container(border=True):
        st.markdown("**공고 자동 검색(네이버)**")
        tab_hunt.summary(res, date.today(), reg.label)
        draft_card(reg.sigungu_cd)
    with st.expander("공고 검색 결과 · 여러 글을 골라 조건 합치기", expanded=bool(res and res.stage == "search" and not (res.auto and res.auto.merged))):
        tab_hunt.panel(reg.sigungu_cd, reg.label, date.today(), o is not None, "home")

    st.divider()
    ready = bool(reg.bjdong_cds)
    a, b = st.columns([1, 2])
    if a.button("후보 건물 찾기 →", type="primary", disabled=not ready, use_container_width=True):
        _go("region")
    b.caption(
        f"{reg.label} · 읍·면·동 {len(reg.bjdong_cds)}곳 선택. 다음 화면에서 '조회·판정'으로 건축물대장을 조회합니다."
        if ready else "읍·면·동을 하나 이상 고르거나 '전체'를 켜세요."
    )
