"""소규모 노후건축물 안전점검 지원 대상 선별 — Streamlit 앱.

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

from app import map_view, sidebar, state, tab_hunt, tab_letters, tab_notice, tab_region  # noqa: E402

SECTIONS = {
    "notice": "① 공고문 분석 & 조건",
    "region": "② 지역 일괄 대조",
    "letters": "③ 안내문 및 결과 리포트",
    "map": "④ 지도",
}

st.set_page_config(page_title="노후건축물 안전점검 대상 선별", layout="wide")
state.load_secrets_into_env()
state.init()

st.title("소규모 노후건축물 안전점검 지원 대상 선별")
st.caption("결과는 '자격 후보'입니다. 최종 선정은 담당자·위원회가 합니다.")

ctx = sidebar.render()
tab_hunt.auto_run(ctx)  # 지역을 고르면 공고 자동 검색·추출(시군구마다 한 번)
section = st.segmented_control(
    "화면", list(SECTIONS), format_func=SECTIONS.get, default="region", key="section", label_visibility="collapsed"
) or "region"

if section == "notice":
    tab_notice.render(ctx)
elif section == "region":
    tab_region.render(ctx)
elif section == "letters":
    tab_letters.render(ctx, tab_region.current_view(ctx)[0])
else:
    map_view.render(ctx, tab_region.current_view(ctx)[0])

st.divider()
st.caption("조회 데이터는 저장되지 않습니다. 새로고침하거나 창을 닫으면 대장 조회 결과와 판정 결과가 사라집니다.")
