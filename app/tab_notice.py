"""탭1 공고문 분석 & 조건 추출 — 이 단계에서는 저장된 공고 JSON 보기와 원문 근거 표시만.

업로드 → 분류 → 추출은 단계 6에서 연결한다.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from app import tab_hunt, tab_upload
from app.state import Ctx
from core.conditions import BUSINESS_TYPE_LABEL, NoticeConditions
from core.notices import load_notices, notice_label

FIELDS = [
    ("local_gov", "지자체"),
    ("program_name", "사업명"),
    ("business_type", "사업유형"),
    ("sigungu_codes", "시군구코드"),
    ("application_period", "접수기간(원문)"),
    ("apply_start", "접수 시작"),
    ("apply_end", "접수 종료"),
    ("min_years", "경과연수(년 이상)"),
    ("max_floors", "층수"),
    ("max_area", "연면적(㎡)"),
    ("use_filter", "용도"),
    ("structure_filter", "구조"),
    ("exclusions", "제외대상"),
    ("selection_method", "선정방식"),
    ("priority_rules", "우선순위(판정에 안 씀)"),
    ("offmap_conditions", "대장 외 조건(현장확인)"),
    ("support_content", "지원내용"),
    ("source_url", "인터넷 주소"),
]


def _value(n: NoticeConditions, key: str) -> str:
    v = getattr(n, key)
    if key == "business_type":
        return BUSINESS_TYPE_LABEL.get(v, "미정") if v else "미정"
    if key == "max_floors" and v is not None:
        return f"{v}층 {'이하' if n.floors_bound == 'LE' else '미만'}"
    if key == "max_area" and v is not None:
        return f"{v:g}㎡ {'이하' if n.area_bound == 'LE' else '미만'}"
    if isinstance(v, list):
        return ", ".join(map(str, v))
    return "" if v is None else str(v)


def render(ctx: Ctx) -> None:
    tab_hunt.render(ctx)
    st.divider()
    tab_upload.render()
    st.divider()
    st.subheader("저장된 공고 보기")
    notices = load_notices()
    if not notices:
        st.info("저장된 공고가 없습니다.")
        return
    ids = [n.notice_id for n in notices]
    default = ids.index(ctx.notice.notice_id) if ctx.notice and ctx.notice.notice_id in ids else 0
    nid = st.selectbox("공고", ids, index=default, format_func=lambda i: notice_label(notices[ids.index(i)], ctx.eval_date))
    n = st.session_state["notice_edits"].get(nid) or notices[ids.index(nid)]
    if not n.reviewed:
        st.markdown(":orange-badge[미검수] 사람이 원문과 대조해 확인하기 전입니다.")
    if nid in st.session_state["notice_edits"]:
        st.markdown(":blue-badge[수정됨] 이 세션에서 담당자가 고친 값입니다.")
    if n.source_url:
        st.markdown(f"**인터넷 주소** [{n.source_url}]({n.source_url})")

    left, right = st.columns([3, 2])
    with left:
        table = pd.DataFrame([{"항목": label, "값": _value(n, key), "키": key} for key, label in FIELDS])
        event = st.dataframe(
            table[["항목", "값"]], hide_index=True, use_container_width=True,
            on_select="rerun", selection_mode="single-row", key=f"notice-fields-{nid}",
        )
        rows = event.selection.rows if event and event.selection else []
    with right:
        st.markdown("**원문 근거**")
        if rows:
            key = table.iloc[rows[0]]["키"]
            ev = n.evidence.get(key)
            st.markdown(f"**{table.iloc[rows[0]]['항목']}**")
            st.info(ev) if ev else st.caption("이 항목의 원문 인용이 없습니다.")
        else:
            st.caption("왼쪽 표에서 항목을 고르면 원문 근거가 나옵니다.")
        others = {k: v for k, v in n.evidence.items() if k not in {f for f, _ in FIELDS}}
        for k, v in others.items():
            st.caption(f"{k}: {v}")
    with st.expander("JSON"):
        st.code(n.model_dump_json(indent=2), language="json")
