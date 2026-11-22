"""소규모 노후건축물 안전점검 지원 대상 선별 — Streamlit 앱.

처음 화면(app/home.py): 지역 선택(도·시·구·동, 이름 검색) | 공고문 올리기 → '공고·조례 검색' 버튼 → '후보 건물 찾기'.
작업 화면: 사이드바(지역·공고·옵션) + 지역 일괄 대조 | 지도 | 안내문(단계 번호는 단계 표시줄에만). 공고 분석·조건 검수는 처음 화면에서.

실행(저장소 루트):  streamlit run app/main.py

화면 전환은 st.tabs 대신 선택 버튼을 쓴다. st.tabs는 숨은 탭까지 매번 모두 그려서
지도(브이월드 경계·folium)와 안내문 처리가 다른 화면을 볼 때도 돌아갔다. 지금은 고른 화면만 그린다.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import streamlit as st  # noqa: E402

from app import home, map_view, motion, sidebar, state, tab_letters, tab_region  # noqa: E402

SECTIONS = {
    "region": "지역 일괄 대조",
    "map": "지도",
    "letters": "안내문·결과 리포트",
}

st.set_page_config(page_title="노후건축물 안전점검 대상 선별", layout="wide")
state.load_secrets_into_env()
state.init()

motion.inject()  # 단계 전환·사이드바·드롭다운 움직임, 실행 중 표시(app/motion.py)


def work() -> None:
    ctx = sidebar.render()
    if ctx is None:
        st.info("왼쪽에서 지역(구·군)을 고르세요. 처음 화면에서 고를 수도 있습니다.")
        if st.button("← 처음 화면으로"):
            st.session_state["stage"] = "home"
            st.rerun()
        return
    st.markdown(f"### {ctx.region_label}")
    motion.step_bar(st.session_state.get("section") or "region", scope="section")
    if st.session_state.get("section") not in SECTIONS:  # 공고 분석·조건 편집은 처음 화면에서 한다
        st.session_state.pop("section", None)
    kwargs = {} if "section" in st.session_state else {"default": "region"}
    section = st.segmented_control(
        "화면", list(SECTIONS), format_func=SECTIONS.get, key="section", label_visibility="collapsed", **kwargs
    ) or "region"
    with motion.view(section, scope="section"):  # 화면 사이를 옮기면 진행 방향으로 들어온다
        if section == "region":
            tab_region.render(ctx)
        elif section == "letters":
            tab_letters.render(ctx, tab_region.current_view(ctx)[0])
        else:
            map_view.render(ctx, tab_region.current_view(ctx)[0])


# 처음 화면(지역 선택 | 공고문 올리기) → '후보 건물 찾기'로 작업 화면
stage = st.session_state.setdefault("stage", "home")
with motion.view(stage):  # 처음 화면 → 작업 화면은 오른쪽에서, 되돌아가면 왼쪽에서
    if stage == "home":
        home.render()
    else:
        work()

st.divider()
st.caption("조회 데이터는 저장되지 않습니다. 새로고침하거나 창을 닫으면 대장 조회 결과와 판정 결과가 사라집니다.")
