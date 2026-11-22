"""탭2 지역 일괄 대조: 조회·판정, 통계, 결과표, 건물 상세, 내보내기."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from app.state import Ctx
from core import building_api
from core.ordinances import SCALE_RULE_LABEL
from core.evaluator import REASON_TEXT, STATUS_LABEL
from core.export import ExportSummary, export_filename, result_table, to_csv_bytes, to_excel_bytes
from core.pipeline import RegionResult, run_region

STATUS_ORDER = ["CANDIDATE", "NEEDS_CHECK", "ORDINANCE_ONLY", "NOT_ELIGIBLE"]


def banners(ctx: Ctx) -> None:
    n, o = ctx.notice, ctx.ordinance
    if n is None:
        st.info("공고가 없어 조례 기준으로 판정합니다." if o else "공고와 조례가 없어 법정 기준(사용승인 후 30년 이상)으로만 판정합니다.")
    else:
        badges = []
        if not n.reviewed:
            badges.append(":orange-badge[미검수]")
        if ctx.notice_edited:
            badges.append(":blue-badge[수정됨]")
        if ctx.test_mode:
            badges.append(":red-badge[시험용 · 다른 지역 공고]")
        link = f" · [원문]({n.source_url})" if n.source_url else ""
        st.markdown(f"**공고** {n.program_name or n.notice_id}{link} " + " ".join(badges))
        state, msg = n.period_status(ctx.eval_date)
        if state == "CLOSED":
            st.warning(f"⚠️ 사업기간 아님 · {msg} 안내문 생성은 막혀 있습니다.")
        elif state == "NOT_STARTED":
            st.warning(f"⚠️ 사업기간 아님 · {msg}")
        elif state == "UNKNOWN":
            st.warning(f"⚠️ 접수기간 확인 불가 · {msg}")
    if o:
        extra = " · 조례 분류 검토 필요" if o.review_needed else ""
        st.caption(f"조례: {o.ordinance_name} ({o.effective_date}) · 규모 기준 {SCALE_RULE_LABEL.get(o.scale_rule_type, o.scale_rule_type)}{extra}"
                   + (f" · {o.note}" if o.note else ""))


def _run(ctx: Ctx, dongs: list[str], fetch: bool) -> RegionResult:
    bar = st.progress(0.0, "준비 중") if fetch else None
    res = run_region(
        ctx.sigungu_cd,
        dongs,
        ctx.notice,
        ctx.ordinance,
        ctx.eval_date,
        st.session_state["raw"],
        (lambda f, t: bar.progress(min(1.0, f), t)) if bar else None,
        results_cache=st.session_state["results"],
        options=ctx.options,
        test_mode=ctx.test_mode,
        fetch=None if fetch else _no_fetch,
    )
    if bar:
        bar.empty()
    return res


def _no_fetch(*_a, **_k):  # 보기 전용 재판정에서는 조회하지 않는다
    raise RuntimeError("조회하지 않은 동")


def detail_panel(row: pd.Series, compact: bool = False, key_prefix: str = "") -> None:
    """건물 상세. compact=True면 좁은 칸(지도 오른쪽)용으로 세로 배치."""
    st.subheader("선택한 건물")
    if compact:
        c1, c2 = st.container(), st.container()
    else:
        c1, c2 = st.columns([1, 1])
    with c1:
        st.markdown(f"**{row.get('platPlc') or ''}**  \n{row.get('newPlatPlc') or ''}")
        spec = {
            "상태": STATUS_LABEL.get(row["status"]),
            "사용승인일": row.get("useAprDay") or "(없음)",
            "경과연수": "확인 필요" if pd.isna(row.get("age_years")) else f"{int(row.get('age_years'))}년",
            "지상/지하층수": f"{row.get('grndFlrCnt')} / {row.get('ugrndFlrCnt')}",
            "연면적(㎡)": row.get("totArea"),
            "주구조": f"{row.get('strctCdNm') or row.get('etcStrct')} → {row.get('structure_std') or '분류 못 함'}",
            "주용도": f"{row.get('mainPurpsCdNm')} / {row.get('etcPurps') or '-'}",
            "대장 구분": f"{row.get('regstrGbCdNm')} · {row.get('mainAtchGbCdNm')}",
            "대장PK": row.get("mgmBldrgstPk"),
        }
        st.table(pd.DataFrame({"항목": list(spec), "값": [str(v) for v in spec.values()]}))
    with c2:
        st.markdown(f"**사유** {row['reason_text']}")
        if row["check_reasons"]:
            st.markdown("**확인필요 사유**")
            for c in row["check_reasons"]:
                st.markdown(f"- {REASON_TEXT.get(c, c)}")
        if row["field_checklist"]:
            st.markdown("**현장확인 체크리스트** (체크는 이 세션에만)")
            for item in row["field_checklist"]:
                key = f"{key_prefix}chk-{row['mgmBldrgstPk']}-{item}"
                st.checkbox(item, key=key)
        for note in row.get("notes") or []:
            st.caption(note)
    nd = {d["조건"]: d for d in row["notice_detail"] or []}
    od = {d["조건"]: d for d in row["ordinance_detail"] or []}
    names = list(dict.fromkeys(list(nd) + list(od)))
    comp = pd.DataFrame(
        [
            {
                "조건": k,
                "공고 기준": nd.get(k, {}).get("기준", ""),
                "조례 기준": od.get(k, {}).get("기준", ""),
                "대장 값": (nd.get(k) or od.get(k) or {}).get("대장값", ""),
                "공고 결과": nd.get(k, {}).get("결과", ""),
                "조례 결과": od.get(k, {}).get("결과", ""),
            }
            for k in names
        ]
    )
    st.markdown("**조건별 비교**")
    st.dataframe(comp, hide_index=True, use_container_width=True)


def current_view(ctx: Ctx) -> tuple[RegionResult | None, list[str]]:
    """지금 보여 줄 판정 결과(조회는 하지 않음). 다른 화면(안내문·지도)도 이걸 쓴다.

    조건이 바뀌면 여기서 재조회 없이 재판정한다(세션의 대장 원본 + 조건별 판정 캐시).
    """
    queried: set = st.session_state["queried"].get(ctx.sigungu_cd, set())
    if not queried:
        return None, []
    show_all = st.session_state.get("show_all", True)
    view = sorted(queried) if show_all else [b for b in ctx.bjdong_cds if b in queried]
    if not view:
        return None, []
    return _run(ctx, view, fetch=False), view


def render(ctx: Ctx) -> RegionResult | None:
    banners(ctx)
    if not ctx.bjdong_cds:
        st.info("왼쪽 사이드바에서 읍·면·동을 하나 이상 고르세요.")
        return None

    try:
        building_api.api_key()
    except building_api.BuildingApiAuthError as e:
        st.error(str(e))
        return None

    queried: set = st.session_state["queried"].setdefault(ctx.sigungu_cd, set())
    new = [b for b in ctx.bjdong_cds if (ctx.sigungu_cd, b) not in st.session_state["raw"]]
    ready = True
    if ctx.all_selected and new:
        key = (ctx.sigungu_cd, tuple(new))
        est = st.session_state["estimate"].get(key)
        if est is None:
            if st.button(f"조회 전 건물 수 확인 (읍·면·동 {len(new)}곳)"):
                with st.spinner("읍·면·동별 건물 수 확인 중"):
                    st.session_state["estimate"][key] = building_api.estimate_calls(ctx.sigungu_cd, new)
                st.rerun()
            ready = False
        else:
            st.warning(f"읍·면·동 {len(new)}곳 · 건물 약 {est['buildings']:,}건 · 건축물대장 조회 약 {est['calls']:,}회(하루 허용량에서 차감)")
            ready = st.checkbox("확인했습니다. 조회를 진행합니다.")

    if st.button("조회·판정", type="primary", disabled=not ready):
        try:
            res = _run(ctx, ctx.bjdong_cds, fetch=True)
        except building_api.BuildingApiAuthError as e:
            st.error(str(e))
            return None
        queried.update(b for b in ctx.bjdong_cds if (ctx.sigungu_cd, b) in st.session_state["raw"])
        st.session_state["failed"].setdefault(ctx.sigungu_cd, {}).update(res.failed_dongs)
        for b in queried:
            st.session_state["failed"][ctx.sigungu_cd].pop(b, None)
        if res.quota_stopped:
            st.error("건축물대장 하루 조회 허용량을 넘어 조회를 멈췄습니다. 받은 동까지만 판정했으니, 나머지 동은 다음 날 다시 조회하세요.")
        elif res.failed_dongs:
            st.error(
                "조회하지 못한 동: "
                + ", ".join(ctx.bjdong_names.get(b, b) for b in res.failed_dongs)
                + " — 잠시 뒤 다시 ‘조회·판정’을 누르세요(받은 동은 다시 조회하지 않습니다)."
            )
            with st.expander("실패 사유"):
                for b, why in res.failed_dongs.items():
                    st.caption(f"{ctx.bjdong_names.get(b, b)}: {why}")
                st.caption("공공데이터포털 건축물대장 서비스가 잠시 응답하지 않을 때가 있습니다. 잠시 뒤 '조회·판정'을 다시 눌러 보세요.")
        st.toast(f"건축물대장 조회 {res.api_calls}회")

    if not queried:
        st.caption("‘조회·판정’을 누르면 대장 조회와 판정을 한 번에 합니다.")
        return None

    st.checkbox(f"이 시군구에서 조회한 동 모두 보기 ({len(queried)}개 동)", value=True, key="show_all")
    res, view = current_view(ctx)
    if res is None or res.df.empty:
        st.info("판정할 건물이 없습니다.")
        return res

    s = res.stats
    cols = st.columns(5)
    cols[0].metric("총 건물 수", f"{s['TOTAL']:,}")
    for c, code in zip(cols[1:], STATUS_ORDER):
        c.metric(STATUS_LABEL[code], f"{s[code]:,}")
    if ctx.test_mode:
        st.caption("시험용: 다른 지역 공고를 적용한 결과입니다.")

    picked = st.multiselect("상태 필터", STATUS_ORDER, default=STATUS_ORDER[:3], format_func=STATUS_LABEL.get)
    df = res.df[res.df["status"].isin(picked)].reset_index(drop=True)
    table = result_table(df)
    event = st.dataframe(
        table,
        hide_index=True,
        use_container_width=True,
        on_select="rerun",
        selection_mode="single-row",
        key=f"table-{ctx.sigungu_cd}",
    )
    rows = event.selection.rows if event and event.selection else []
    if rows:
        detail_panel(df.iloc[rows[0]])

    with st.expander("분류하지 못한 구조·용도, 조회 실패한 동, 경고"):
        st.write("분류하지 못한 구조(대장 값: 건수)", dict(res.unmapped_structures) or "없음")
        st.write("분류하지 못한 용도(대장 값: 건수)", dict(res.unmapped_uses) or "없음")
        failed = st.session_state["failed"].get(ctx.sigungu_cd, {})
        st.write("실패한 동", {ctx.bjdong_names.get(k, k): v for k, v in failed.items()} or "없음")
        for w in res.warnings:
            st.caption(w)

    names = [ctx.bjdong_names.get(b, b) for b in view]
    summary = ExportSummary(
        region=f"{ctx.region_label} " + (names[0] if len(names) == 1 else f"{names[0]} 외 {len(names) - 1}개 동"),
        eval_date=ctx.eval_date,
        notice=ctx.notice,
        ordinance=ctx.ordinance,
        notice_edited=ctx.notice_edited,
        test_mode=ctx.test_mode,
        unmapped_structures=res.unmapped_structures,
        unmapped_uses=res.unmapped_uses,
        failed_dongs=st.session_state["failed"].get(ctx.sigungu_cd, {}),
    )
    c1, c2, c3 = st.columns([1, 1, 2])
    include_ne = c3.checkbox("엑셀에 '비해당' 시트도 넣기", value=True)
    df_all = res.df
    # 파일은 버튼을 누를 때만 만든다(매번 다시 그릴 때 Excel을 만들지 않도록). 디스크에는 쓰지 않는다.
    c1.download_button(
        "Excel 내려받기",
        lambda: to_excel_bytes(df_all, summary, include_not_eligible=include_ne),
        file_name=export_filename(ctx.sigungu_name, names, ctx.eval_date),
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        on_click="ignore",
    )
    c2.download_button(
        "CSV 내려받기",
        lambda: to_csv_bytes(df_all),
        file_name=export_filename(ctx.sigungu_name, names, ctx.eval_date, "csv"),
        mime="text/csv",
        on_click="ignore",
    )
    return res
