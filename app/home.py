"""처음 화면: 지역 선택(도 → 시·군 → 구·군 → 읍·면·동, 이름 검색) | 공고문 직접 올리기.

지역(구·군)을 고르고 '공고·조례 검색'을 누르면 조례(소규모 노후건축물 점검 대상 규모)를 보여 주고, 공고를 찾아 조건을 추출·합성한다.
'후보 건물 찾기'를 누르면 작업 화면(② 지역 일괄 대조)으로 넘어간다.
"""

from __future__ import annotations

from datetime import date

import streamlit as st

from app import motion, region_picker, tab_hunt, tab_upload
from core import ordinances
from core.ordinances import OrdinanceConditions

HERO = """
<div style="padding:24px 0 0 0">
  <h1 style="font-size:2.3rem;font-weight:800;line-height:1.25;margin:0 0 10px 0;padding:0">소규모 노후건축물<br>안전점검 지원 대상 찾기</h1>
  <p style="font-size:1.05rem;opacity:0.82;max-width:760px;margin:0">
    지역을 고르면 그 지역 조례와 올해 공고를 찾아 지원 조건을 뽑고, 건축물대장에서 조건에 맞는 건물을 골라 드립니다.
    결과는 '자격 후보'이며 최종 선정은 담당자·위원회가 합니다.
  </p>
</div>
"""


def _go(section: str) -> None:
    st.session_state["stage"] = "work"
    st.session_state["screen"] = section
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
        st.caption(f"확인할 점 {len(draft['issues'])}건 · 아래 ② 조건 검수에서 원문 근거와 함께 봅니다.")


def _draft_for(sgg: str | None) -> dict | None:
    """이 지역에 걸린 미검수 초안(없으면 None). sgg=None이면 지역과 상관없이."""
    draft = st.session_state.get("draft")
    if not draft:
        return None
    n = draft["notice"]
    if sgg and n.sigungu_codes and sgg not in n.sigungu_codes:
        return None
    return draft


def _reviewed_for(sgg: str | None, origin: str | None = None):
    """이 지역에서 '검수 완료로 저장'한 공고(없으면 None)."""
    r = st.session_state.get("reviewed")
    if not r or (origin and r.get("origin") != origin):
        return None
    n = r["notice"]
    if sgg and sgg not in n.sigungu_codes:
        return None
    return n


def review_editor(sgg: str | None) -> None:
    """② 추출한 조건 검수·수정(원문 근거, 검수 완료로 저장). 끝내야 '후보 건물 찾기'가 열린다."""
    draft = _draft_for(sgg)
    if draft is not None:
        st.markdown("##### ② 조건 검수")
        tab_upload.editor(draft)
        return
    n = _reviewed_for(sgg)
    if n is not None:
        st.success(f"② 검수 완료 · {n.program_name or n.notice_id} — 이 조건으로 후보 건물을 찾습니다.", icon=":material/task_alt:")


MODE_KEY = "home_mode"  # None | "region" | "upload"
CHOICES = {
    "region": (":material/location_on:", "지역 선택", "도·시·구·동을 고르고 검색하면 조례와 공고를 찾습니다"),
    "upload": (":material/upload_file:", "공고문 직접 올리기", "가진 공고 파일에서 조건과 지역을 바로 뽑습니다"),
}

# 고르기 카드 + 펼침 애니메이션. 펼친 칸은 처음 그려질 때만 내려오며 나타난다(같은 칸 안의 조작에는 다시 움직이지 않음)
CSS = """
<style>
@keyframes home-drop {
  from { opacity: 0; transform: translateY(-14px) scaleY(0.96); clip-path: inset(0 0 100% 0); }
  to   { opacity: 1; transform: none; clip-path: inset(0 0 0 0); }
}
[class*="st-key-home-pick-"] button {
  min-height: 112px; width: 100%; padding: 18px 22px; border-radius: 14px;
  justify-content: flex-start; text-align: left; white-space: normal;
  transition: box-shadow .18s var(--m-ease), border-color .18s var(--m-ease), background-color .18s var(--m-ease);
}
[class*="st-key-home-pick-"] button p { font-size: 1.05rem; line-height: 1.45; }
[class*="st-key-home-pick-"] button div, [class*="st-key-home-pick-"] button p {
  white-space: normal; overflow: visible; text-overflow: clip; text-align: left;
}
[class*="st-key-home-pick-"] button:hover { box-shadow: 0 6px 18px rgba(0,0,0,.14); }
[class*="st-key-home-pick-"] button::after {
  content: "expand_more"; content: "expand_more" / ""; /* 아이콘 글자는 화면낭독기 이름에서 뺀다(구형 브라우저는 앞 줄) */
  font-family: "Material Symbols Rounded"; font-size: 1.6rem; margin-left: auto; padding-left: 12px;
  transition: transform var(--m-panel) var(--m-ease);
}
[class*="st-key-home-pick-"] button p { word-break: keep-all; overflow-wrap: break-word; }
[class*="st-key-home-pick-"] button > div { justify-content: flex-start; flex: 1 1 auto; min-width: 0; }
/* 가운데 '또는'은 글자 폭만큼만 차지하고, 두 카드가 나머지를 나눈다. 폭이 좁으면 위아래로 쌓는다(창 크기가 아니라 칸 폭 기준) */
.st-key-home-choices { container-type: inline-size; }
.st-key-home-choices [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:nth-child(2) {
  flex: 0 0 auto !important; width: auto !important; min-width: 0 !important;
}
.st-key-home-choices [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:not(:nth-child(2)) {
  flex: 1 1 0 !important; width: auto !important; min-width: 0 !important;
}
@container (max-width: 680px) {
  .st-key-home-choices [data-testid="stHorizontalBlock"] { flex-direction: column; align-items: stretch; }
  .st-key-home-choices [data-testid="stHorizontalBlock"] > [data-testid="stColumn"] { width: 100% !important; flex: 0 0 auto !important; }
  .st-key-home-choices .home-or { height: auto; padding: 2px 0; }
}
.sr-only { position: absolute; width: 1px; height: 1px; margin: -1px; padding: 0; overflow: hidden; clip-path: inset(50%); white-space: nowrap; border: 0; }
.home-or { display: flex; align-items: center; justify-content: center; height: 112px; }
.home-or span { padding: 6px 14px; border-radius: 999px; font-weight: 700; font-size: .95rem;
  white-space: nowrap; word-break: keep-all; writing-mode: horizontal-tb;
  background: rgba(127,127,127,.14); }
.st-key-home-panel-region, .st-key-home-panel-upload {
  animation: home-drop var(--m-panel) var(--m-ease) backwards; transform-origin: top center;
}
@media (max-width: 640px) { .home-or { height: auto; padding: 2px 0; } }
@media (prefers-reduced-motion: reduce) {
  .st-key-home-panel-region, .st-key-home-panel-upload { animation: view-fade 160ms ease-out backwards; }
  [class*="st-key-home-pick-"] button, [class*="st-key-home-pick-"] button::after { transition: none; }
}
</style>
"""


def _pick(mode: str) -> None:
    st.session_state[MODE_KEY] = None if st.session_state.get(MODE_KEY) == mode else mode  # 다시 누르면 접기


def choice_buttons() -> str | None:
    mode = st.session_state.get(MODE_KEY)
    st.markdown(CSS, unsafe_allow_html=True)
    if mode:  # 고른 카드의 화살표를 뒤집는다(버튼은 화면에 남아 있어 회전이 부드럽게 보인다)
        st.markdown(f"<style>.st-key-home-pick-{mode} button::after{{transform:rotate(180deg)}}</style>", unsafe_allow_html=True)
    left, mid, right = st.container(key="home-choices").columns([10, 2, 10], vertical_alignment="center")
    for col, m in ((left, "region"), (right, "upload")):
        icon, title, desc = CHOICES[m]
        col.button(
            f"**{title}**  \n{desc}", key=f"home-pick-{m}", icon=icon, on_click=_pick, args=(m,),
            type="primary" if mode == m else "secondary", use_container_width=True,
        )
    mid.markdown('<div class="home-or"><span>또는</span></div>', unsafe_allow_html=True)
    # Streamlit 버튼에는 aria-expanded를 달 수 없어, 펼침 상태를 화면낭독기에 상태 문구로 알린다(늘 같은 자리에 두고 글만 바꾼다)
    said = f"{CHOICES[mode][1]} 칸을 펼쳤습니다. 카드 아래에서 이어서 고르세요." if mode else ""
    st.markdown(f'<p class="sr-only" role="status" aria-live="polite">{said}</p>', unsafe_allow_html=True)
    return mode


REVIEW_FIRST = "먼저 위 ② 조건 검수에서 원문과 대조하고 '검수 완료로 저장'을 누르세요."


def _start_row(ready: bool, ready_msg: str, wait_msg: str, sgg: str | None = None) -> None:
    """③ 후보 건물 찾기. 미검수 초안이 있으면 잠근다(검수 → 대조 순서)."""
    st.divider()
    pending = _draft_for(sgg) is not None
    a, b = st.columns([1, 2])
    if a.button("③ 후보 건물 찾기 →", type="primary", disabled=pending or not ready, use_container_width=True, key="home-start"):
        _go("region")
    b.caption(REVIEW_FIRST if pending else ready_msg if ready else wait_msg)


def _region_panel() -> None:
    with st.container(border=True, key="home-panel-region"):
        reg = region_picker.render(st, "home", row=True)
        clicked = False
        if reg.ready:
            b, _ = st.columns([1, 2])
            clicked = b.button("공고·조례 검색", type="primary", icon=":material/search:", key="home-search", use_container_width=True)
    if not reg.ready:
        return
    o = ordinances.get_ordinance(reg.sigungu_cd)
    if clicked:
        tab_hunt.search(reg.sigungu_cd, reg.label, date.today(), o is not None)
    res = tab_hunt.result(reg.sigungu_cd)
    if res is None:
        return

    st.markdown(f"##### ① {reg.label} · 조례와 공고 조건")
    c1, c2 = st.columns([2, 3], gap="large")
    with c1, st.container(border=True):
        ordinance_card(o)
    with c2, st.container(border=True):
        st.markdown("**공고 검색(네이버)**")
        tab_hunt.summary(res, date.today(), reg.label)
        draft_card(reg.sigungu_cd)
    review_editor(reg.sigungu_cd)
    with st.expander("공고 검색 결과 · 여러 글을 골라 조건 합치기", expanded=bool(res.stage == "search" and not (res.auto and res.auto.merged))):
        tab_hunt.panel(reg.sigungu_cd, reg.label, date.today(), o is not None, "home")
    _start_row(
        bool(reg.bjdong_cds),
        f"{reg.label} · 읍·면·동 {len(reg.bjdong_cds)}곳 선택. 다음 화면에서 '조회·판정'으로 건축물대장을 조회합니다.",
        "읍·면·동을 하나 이상 고르거나 '전체'를 켜세요.",
        reg.sigungu_cd,
    )


def _upload_panel() -> None:
    with st.container(border=True, key="home-panel-upload"):
        st.caption("HWP·HWPX·PDF·DOCX·XLSX·이미지. 여러 파일은 한 공고로 묶어 추출하고, 공고의 지자체를 지역으로 넣습니다.")
        tab_upload.upload_box("home")
    draft = st.session_state.get("draft")
    uploaded = draft is not None and draft.get("origin") == "upload"
    saved = _reviewed_for(None, origin="upload")
    if not uploaded and saved is None:
        return
    reg = region_picker.current()
    st.markdown("##### ① 공고에서 뽑은 조건")
    c1, c2 = st.columns([2, 3], gap="large")
    with c2, st.container(border=True):
        if uploaded:
            draft_card(None)
        else:
            st.markdown(f"**공고 조건** · {saved.program_name or saved.notice_id} :green-badge[검수 완료]")
    with c1, st.container(border=True):
        if reg.ready:
            st.markdown(f"**지역** {reg.label} · 읍·면·동 {len(reg.bjdong_cds)}곳")
            st.caption("동을 바꾸려면 위에서 '지역 선택'을 누르세요(공고에서 읽은 지역이 들어 있습니다).")
            ordinance_card(ordinances.get_ordinance(reg.sigungu_cd))
        else:
            st.warning("공고에서 지자체를 찾지 못했습니다. 위에서 '지역 선택'을 눌러 지역을 고르세요.")
    review_editor(None)
    _start_row(reg.ready and bool(reg.bjdong_cds), f"{reg.label} · 읍·면·동 {len(reg.bjdong_cds)}곳.", "지역을 먼저 고르세요.")


def render() -> None:
    st.markdown(HERO, unsafe_allow_html=True)
    motion.step_bar("home")
    mode = choice_buttons()
    if mode == "region":
        _region_panel()
    elif mode == "upload":
        _upload_panel()
