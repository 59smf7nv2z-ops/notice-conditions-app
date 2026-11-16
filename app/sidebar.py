"""사이드바: 지역 선택, 공고 선택, 판정 기준일, 옵션, 조건 편집기."""

from __future__ import annotations

from datetime import date

import streamlit as st

from app.state import Ctx, clear
from core import ordinances, regions
from core.conditions import NoticeConditions
from core.evaluator import EvalOptions
from core.notices import load_notices, notice_label, notices_for

NO_NOTICE = "__none__"


def _bound_select(container, label: str, value: str, key: str) -> str:
    opts = ["LE", "LT"]
    names = {"LE": "이하", "LT": "미만"}
    return container.selectbox(label, opts, index=opts.index(value), format_func=names.get, key=key)


def _editor(n: NoticeConditions) -> None:
    """담당자 수정은 세션에만 반영한다. 수정본은 JSON 다운로드로만 내보낸다."""
    edits: dict = st.session_state["notice_edits"]
    cur = edits.get(n.notice_id, n)
    with st.sidebar.expander("조건 편집기" + (" · 수정됨" if n.notice_id in edits else ""), expanded=False):
        with st.form(f"edit-{n.notice_id}"):
            min_years = st.number_input("경과연수(년 이상)", 0, 100, cur.min_years or 0)
            c1, c2 = st.columns(2)
            max_floors = c1.number_input("층수", 0, 100, cur.max_floors or 0, help="0 = 조건 없음")
            fb = _bound_select(c2, "층수 경계", cur.floors_bound, f"fb-{n.notice_id}")
            c3, c4 = st.columns(2)
            max_area = c3.number_input("연면적(㎡)", 0.0, 100000.0, float(cur.max_area or 0), help="0 = 조건 없음")
            ab = _bound_select(c4, "연면적 경계", cur.area_bound, f"ab-{n.notice_id}")
            use = st.text_input("용도(쉼표 구분)", ", ".join(cur.use_filter))
            strc = st.text_input("구조(쉼표 구분)", ", ".join(cur.structure_filter))
            coll = st.checkbox("집합건물 제외", bool(cur.collective_excluded))
            offmap = st.text_area("대장 외 조건(줄마다 하나)", "\n".join(cur.offmap_conditions))
            d1, d2 = st.columns(2)
            start = d1.date_input("접수 시작", cur.apply_start, format="YYYY-MM-DD")
            end = d2.date_input("접수 종료", cur.apply_end, format="YYYY-MM-DD")
            if st.form_submit_button("세션에 반영"):
                split = lambda s: [x.strip() for x in s.split(",") if x.strip()]  # noqa: E731
                try:
                    edits[n.notice_id] = cur.model_copy(
                        update={
                            "min_years": int(min_years) or None,
                            "max_floors": int(max_floors) or None,
                            "floors_bound": fb,
                            "max_area": float(max_area) or None,
                            "area_bound": ab,
                            "use_filter": split(use),
                            "structure_filter": split(strc),
                            "collective_excluded": coll or None,
                            "offmap_conditions": [x.strip() for x in offmap.splitlines() if x.strip()],
                            "apply_start": start,
                            "apply_end": end,
                        }
                    )
                    NoticeConditions.model_validate(edits[n.notice_id].model_dump())
                    st.rerun()
                except ValueError as e:
                    edits.pop(n.notice_id, None)
                    st.error(f"수정값 오류: {e}")
        if n.notice_id in edits:
            st.download_button(
                "수정본 JSON 내려받기",
                edits[n.notice_id].model_dump_json(indent=2).encode("utf-8"),
                file_name=f"{n.notice_id}_수정본.json",
                mime="application/json",
            )
            if st.button("수정 취소"):
                edits.pop(n.notice_id)
                st.rerun()


def render() -> Ctx:
    sb = st.sidebar
    sb.header("지역·조건")
    sidos = regions.list_sido()
    sido = sb.selectbox("시·도", sidos, index=sidos.index("서울특별시") if "서울특별시" in sidos else 0)
    sggs = regions.list_sigungu(sido)
    names = [n for _, n in sggs]
    default_sgg = names.index("종로구") if "종로구" in names else 0
    sgg_name = sb.selectbox("시·군·구", names, index=default_sgg)
    sgg = sggs[names.index(sgg_name)][0]

    dongs = regions.list_bjdong(sgg)
    dong_names = dict(dongs)
    all_sel = sb.checkbox("법정동 전체 선택", key=f"all-{sgg}")
    if all_sel:
        bjds = [c for c, _ in dongs]
        sb.caption(f"{len(bjds)}개 동 선택됨")
    else:
        default = [c for c, n in dongs if n == "청운동"][:1]
        bjds = sb.multiselect("법정동(여러 개)", [c for c, _ in dongs], default=default, format_func=dong_names.get, key=f"dongs-{sgg}")

    eval_date = sb.date_input("판정 기준일", date.today(), format="YYYY-MM-DD")

    all_notices = load_notices()
    local = notices_for(sgg, all_notices)
    test_mode = sb.checkbox("다른 지역 공고 적용(시험용)", help="결과 전체에 '시험용'이 표시됩니다.")
    pool = all_notices if test_mode else local
    labels = {NO_NOTICE: "공고 없이 조례 기준"} | {n.notice_id: notice_label(n, eval_date) for n in pool}
    order = [n.notice_id for n in pool] + [NO_NOTICE]  # 접수 시작일이 최신인 공고가 기본
    chosen = sb.selectbox("공고", order, format_func=labels.get, key=f"notice-{sgg}-{test_mode}")
    notice = next((n for n in pool if n.notice_id == chosen), None)
    is_test = bool(test_mode and notice and sgg not in notice.sigungu_codes)

    edited = False
    if notice:
        _editor(notice)
        if notice.notice_id in st.session_state["notice_edits"]:
            notice = st.session_state["notice_edits"][notice.notice_id]
            edited = True

    with sb.expander("판정 옵션"):
        include_annex = st.checkbox("부속건축물도 판정", False)
        excl_coll = st.checkbox("집합건물 제외(공고·조례 공통)", False)

    sb.divider()
    if sb.button("세션 데이터 지우기", help="조회한 대장·판정 결과·수정본을 모두 지웁니다."):
        clear()
        st.rerun()

    return Ctx(
        sido=sido,
        sigungu_cd=sgg,
        sigungu_name=sgg_name,
        bjdong_cds=bjds,
        bjdong_names=dong_names,
        all_selected=all_sel,
        eval_date=eval_date,
        notice=notice,
        notice_edited=edited,
        test_mode=is_test,
        ordinance=ordinances.get_ordinance(sgg),
        options=EvalOptions(include_annex=include_annex, exclude_collective=excl_coll or None),
    )
