"""탭4 지도 드릴다운 (folium + streamlit-folium).

Level 1  시군구 경계 + 법정동 폴리곤(조회·판정한 동은 1차 후보 수로 채색, 미조회 동은 회색). 동을 누르면 그 동 선택
Level 2  법정동 단위 대상 핀(MarkerCluster, 상태별 모양·색: 1차 후보 물방울 핀 ✓, 확인 필요 네모 핀 ?, 조례만 원형 핀, 상태 토글)
Level 3  핀·표에서 건물을 고르면 오른쪽 상세 패널

좌표·경계는 st.session_state에만 둔다(브이월드 지오코더 응답은 저장 금지). 배경지도는 OSM:
브이월드 배경지도 타일은 키가 브라우저에 노출되므로 쓰지 않는다.
"""

from __future__ import annotations

import folium
import pandas as pd
import streamlit as st
from folium.plugins import BeautifyIcon, MarkerCluster
from streamlit_folium import st_folium

from app.state import Ctx
from app.tab_region import detail_panel
from core import boundaries, geocode, regions
from core.evaluator import STATUS_LABEL
from core.export import result_table
from core.pipeline import RegionResult, run_region

COLORS = {"CANDIDATE": "#2e7d32", "NEEDS_CHECK": "#ef6c00", "ORDINANCE_ONLY": "#1565c0"}
PRIORITY = ["CANDIDATE", "NEEDS_CHECK", "ORDINANCE_ONLY"]
# (핀 모양, 안의 아이콘, 범례 기호): 색을 못 구분해도 모양으로 구분되게
SHAPES = {"CANDIDATE": ("marker", "check", "▼"), "NEEDS_CHECK": ("rectangle", "question", "■"), "ORDINANCE_ONLY": ("circle", "info", "●")}


def pin_icon(status: str) -> BeautifyIcon:
    shape, icon, _ = SHAPES[status]
    return BeautifyIcon(
        icon=icon, icon_shape=shape, border_color="#ffffff", border_width=1.5,
        background_color=COLORS[status], text_color="#ffffff", inner_icon_style="font-size:11px;",
    )
CLUSTER_WARN = 2000


def _init() -> None:
    for k in ("geo", "bounds"):
        st.session_state.setdefault(k, {})
    st.session_state.setdefault("map_pick", None)  # 선택한 필지 키
    st.session_state.setdefault("letter_pins", set())  # 지도에서 안내문 대상에 추가한 대장PK


def _banner(ctx: Ctx) -> None:
    n, o = ctx.notice, ctx.ordinance
    parts = []
    if n:
        bound = lambda v, b, u: f"{v:g}{u} {'이하' if b == 'LE' else '미만'}" if isinstance(v, float) else f"{v}{u} {'이하' if b == 'LE' else '미만'}"  # noqa: E731
        nums = [f"{n.min_years}년 이상" if n.min_years else ""]
        nums += [bound(n.max_floors, n.floors_bound, "층") if n.max_floors else "", bound(n.max_area, n.area_bound, "㎡") if n.max_area else ""]
        code, _ = n.period_status(ctx.eval_date)
        state = {"OPEN": "접수 중", "NOT_STARTED": "접수 전", "CLOSED": "접수 마감", "UNKNOWN": "기간 확인 불가"}[code]
        period = f"접수 {n.apply_start or '?'}~{n.apply_end or '?'}" if (n.apply_start or n.apply_end) else "접수기간 미상"
        parts.append(f"**{n.program_name or n.notice_id}** · {period} ({state}) · {'검수 완료' if n.reviewed else '미검수'}")
        parts.append("핵심 조건: " + ", ".join(x for x in nums if x))
    else:
        parts.append("공고 없음 – 조례 기준 판정" if o else "공고·조례 없음 – 법정 기준(30년)")
    if o:
        parts.append(f"조례 규모 유형: {o.scale_rule_type}")
    if ctx.test_mode:
        parts.append(":red-badge[시험용]")
    st.markdown("  \n".join(parts))


def _emd_counts(res: RegionResult | None, sgg: str) -> dict[str, dict[str, int]]:
    """읍면동 경계 코드(8자리) → 상태별 건수."""
    out: dict[str, dict[str, int]] = {}
    if res is None or res.df.empty:
        return out
    for b, s in zip(res.df["bjdongCd"], res.df["status"]):
        e = boundaries.emd_code(sgg, str(b))
        out.setdefault(e, {}).setdefault(s, 0)
        out[e][s] += 1
    return out


def _green(n: int, mx: int) -> str:
    if n <= 0:
        return "#e8f5e9"
    t = min(1.0, n / max(1, mx))
    shades = ["#c8e6c9", "#81c784", "#4caf50", "#2e7d32", "#1b5e20"]
    return shades[min(len(shades) - 1, int(t * (len(shades) - 1) + 0.5))]


def _parcels(res: RegionResult, statuses: list[str]) -> pd.DataFrame:
    df = res.df[res.df["status"].isin(statuses)]
    return geocode.attach_coords(df, st.session_state["geo"])


def render(ctx: Ctx, res: RegionResult | None) -> None:
    _init()
    _banner(ctx)
    sgg = ctx.sigungu_cd
    try:
        sig = boundaries.sigungu_boundary(sgg, cache=st.session_state["bounds"])
        emd = boundaries.emd_boundaries(sgg, cache=st.session_state["bounds"])
    except boundaries.BoundaryError as e:
        st.error(str(e))
        return

    queried: set = st.session_state["queried"].get(sgg, set())
    queried_emd = {boundaries.emd_code(sgg, b) for b in queried}
    counts = _emd_counts(res, sgg)
    mx = max((c.get("CANDIDATE", 0) for c in counts.values()), default=0)

    # --- 상태 토글 · 좌표 가져오기 ---------------------------------------------
    t1, t2, t3, t4 = st.columns([1, 1, 1, 2])
    show = [s for s, c, d in (("CANDIDATE", t1, True), ("NEEDS_CHECK", t2, True), ("ORDINANCE_ONLY", t3, False))
            if c.checkbox(STATUS_LABEL[s], value=d, key=f"map-show-{s}")]
    if res is not None and not res.df.empty and show:
        pending = geocode.pending_parcels(res.df, st.session_state["geo"], tuple(show))
        if pending:
            if t4.button(f"지도 좌표 가져오기 (필지 {len(pending)}개, 호출 최대 {2 * len(pending)}회)", type="primary"):
                bar = st.progress(0.0, "좌표 조회 중")
                try:
                    g = geocode.geocode_buildings(
                        res.df, st.session_state["geo"], statuses=tuple(show),
                        progress=lambda d, t: bar.progress(d / t, f"좌표 조회 {d}/{t}"),
                    )
                except geocode.GeocodeAuthError as e:
                    st.error(str(e))
                    g = None
                bar.empty()
                if g and g.stopped:
                    st.error(g.stopped)
                elif g:
                    st.session_state.setdefault("geo_msg", {})[sgg] = (
                        f"지오코더 호출 {g.calls}회 · 좌표 {g.found}개 · 못 찾음 {len(g.not_found)}개"
                        + (f" · 오류 {len(g.errors)}개" if g.errors else "")
                    )
                    st.rerun()
        else:
            t4.caption(st.session_state.get("geo_msg", {}).get(sgg) or "표시할 건물의 좌표를 모두 받았습니다.")

    parcels = _parcels(res, show) if res is not None and not res.df.empty else pd.DataFrame()
    mapped = parcels[parcels["geo_status"] == "OK"] if not parcels.empty else parcels

    # --- 지도 --------------------------------------------------------------
    left, right = st.columns([2, 1])
    with left:
        # 탭이 숨겨진 상태에서 지도가 만들어지면 fit_bounds가 먹지 않는다 → 중심·확대 수준을 직접 지정
        bbox = _bbox(sig)
        home = ((bbox[0][0] + bbox[1][0]) / 2, (bbox[0][1] + bbox[1][1]) / 2) if bbox else (36.5, 127.8)
        home_zoom = _zoom_for(bbox) if bbox else 7
        m = folium.Map(location=home, zoom_start=home_zoom, tiles="OpenStreetMap", control_scale=True)
        folium.GeoJson(sig, name="시군구 경계", style_function=lambda f: {"color": "#37474f", "weight": 2, "fill": False}).add_to(m)
        emd_feats = []
        for f in emd["features"]:
            code = f["properties"]["emd_cd"]
            c = counts.get(code, {})
            f = dict(f, properties=dict(f["properties"], 후보=c.get("CANDIDATE", 0), 확인필요=c.get("NEEDS_CHECK", 0),
                                         상태="조회·판정 완료" if code in queried_emd else "미조회"))
            emd_feats.append(f)
        folium.GeoJson(
            {"type": "FeatureCollection", "features": emd_feats},
            name="법정동",
            style_function=lambda f: {
                "color": "#546e7a", "weight": 1, "fillOpacity": 0.45,
                "fillColor": _green(f["properties"]["후보"], mx) if f["properties"]["상태"] != "미조회" else "#bdbdbd",
            },
            highlight_function=lambda f: {"weight": 3, "color": "#000"},
            tooltip=folium.GeoJsonTooltip(fields=["full_nm", "상태", "후보", "확인필요"], aliases=["법정동", "상태", "1차 후보", "확인필요"]),
        ).add_to(m)

        if not mapped.empty:
            if len(mapped) >= CLUSTER_WARN:
                st.warning(f"표시할 건물이 {len(mapped):,}개입니다. 클러스터로 묶어 표시합니다.")
            cluster = MarkerCluster(name="대상 건물", options={"disableClusteringAtZoom": 18}).add_to(m)
            for key, g in mapped.groupby("parcel_key", sort=False):
                best = min(g["status"], key=PRIORITY.index)
                first = g.iloc[0]
                pks = ",".join(g["mgmBldrgstPk"].astype(str))
                label = STATUS_LABEL[best] + (f" 외 {len(g) - 1}동" if len(g) > 1 else "")
                folium.Marker(
                    [first["lat"], first["lng"]], icon=pin_icon(best),
                    tooltip=f"{first['platPlc']} · {label} · PK:{pks}",
                ).add_to(cluster)

        pick = st.session_state["map_pick"]
        center, zoom = home, home_zoom
        if pick is not None and not mapped.empty and (mapped["parcel_key"] == pick).any():
            r0 = mapped[mapped["parcel_key"] == pick].iloc[0]
            center, zoom = (r0["lat"], r0["lng"]), 18
        legend = "".join(
            f'<span style="color:{COLORS[s]}">{SHAPES[s][2]}</span> {STATUS_LABEL[s]}&nbsp;&nbsp;' for s in PRIORITY
        ) + '<span style="color:#bdbdbd">■</span> 미조회 동'
        m.get_root().html.add_child(folium.Element(
            f'<div style="position:fixed;bottom:18px;left:18px;z-index:9999;background:#fff;padding:6px 10px;'
            f'border-radius:6px;font-size:12px;box-shadow:0 1px 4px rgba(0,0,0,.3)">{legend}</div>'
        ))
        out = st_folium(
            m, height=620, use_container_width=True, center=center, zoom=zoom,
            returned_objects=["last_object_clicked_tooltip", "last_active_drawing"], key=f"map-{sgg}",
        )

    # --- 클릭 처리 ------------------------------------------------------------
    tip = (out or {}).get("last_object_clicked_tooltip") or ""
    tip_changed = tip != st.session_state.get("map_last_tip")
    st.session_state["map_last_tip"] = tip
    if tip_changed and "PK:" in tip and not mapped.empty:
        pks = tip.split("PK:")[-1].strip().split(",")
        hit = mapped[mapped["mgmBldrgstPk"].astype(str).isin(pks)]
        if not hit.empty and hit.iloc[0]["parcel_key"] != st.session_state["map_pick"]:
            st.session_state["map_pick"] = hit.iloc[0]["parcel_key"]
            st.rerun()
    drawn = (out or {}).get("last_active_drawing") or {}
    clicked_emd = (drawn.get("properties") or {}).get("emd_cd")

    with right:
        if clicked_emd:
            _dong_panel(ctx, clicked_emd, queried)
        pick = st.session_state["map_pick"]
        if pick is not None and not parcels.empty and (parcels["parcel_key"] == pick).any():
            rows = parcels[parcels["parcel_key"] == pick]
            if len(rows) > 1:
                i = st.selectbox(
                    f"이 필지의 건물 {len(rows)}동", range(len(rows)),
                    format_func=lambda j: f"{rows.iloc[j]['dongNm'] or '동명 없음'} · {STATUS_LABEL[rows.iloc[j]['status']]}",
                )
            else:
                i = 0
            row = rows.iloc[i]
            detail_panel(row, compact=True, key_prefix="map-")
            pk = str(row["mgmBldrgstPk"])
            pins: set = st.session_state["letter_pins"]
            if pk in pins:
                if st.button("안내문 대상에서 빼기"):
                    pins.discard(pk)
                    st.rerun()
            elif row["status"] in ("CANDIDATE", "NEEDS_CHECK") and st.button("안내문 대상에 추가", type="primary"):
                pins.add(pk)
                st.rerun()
            if pins:
                st.caption(f"지도에서 고른 안내문 대상 {len(pins)}건 (탭3에서 사용)")
        elif not clicked_emd:
            st.caption("핀을 누르면 건물 상세가, 법정동을 누르면 동 정보가 여기에 나옵니다.")

    # --- 표 · 좌표 없음 ----------------------------------------------------------
    if parcels.empty:
        if res is None or res.df.empty:
            st.info("탭2에서 조회·판정을 하거나, 지도에서 법정동을 눌러 조회하세요.")
        return
    st.markdown("**지도 대상 건물** (행을 고르면 상세 패널이 열리고 지도가 그 건물로 이동)")
    view = parcels.reset_index(drop=True)
    table = result_table(view)
    table.insert(0, "좌표", view["geo_status"].values)
    ev = st.dataframe(table, hide_index=True, use_container_width=True, on_select="rerun",
                      selection_mode="single-row", key=f"map-table-{sgg}")
    sel = ev.selection.rows if ev and ev.selection else []
    # 표 선택은 다시 그려도 남아 있으므로, 선택이 '바뀌었을 때'만 지도 선택을 덮어쓴다(핀 클릭이 우선)
    sel_key = view.iloc[sel[0]]["parcel_key"] if sel else None
    if sel_key != st.session_state.get("map_table_sel"):
        st.session_state["map_table_sel"] = sel_key
        if sel_key is not None and sel_key != st.session_state["map_pick"]:
            st.session_state["map_pick"] = sel_key
            st.rerun()
    missing = view[view["geo_status"] == "좌표 없음"]
    if not missing.empty:
        with st.expander(f"좌표 없음 {len(missing)}건 (표에는 있고 지도에는 없음)"):
            st.dataframe(result_table(missing)[["지번주소", "도로명주소", "상태", "대장PK"]], hide_index=True)


def _dong_panel(ctx: Ctx, emd_cd: str, queried: set) -> None:
    sgg = ctx.sigungu_cd
    dongs = [(b, n) for b, n in regions.list_bjdong(sgg) if boundaries.emd_code(sgg, b) == emd_cd]
    if not dongs:
        return
    names = ", ".join(n for _, n in dongs[:5]) + (f" 외 {len(dongs) - 5}개" if len(dongs) > 5 else "")
    st.markdown(f"**선택한 법정동**: {names}")
    todo = [b for b, _ in dongs if b not in queried]
    if not todo:
        st.caption("조회·판정 완료")
        return
    if st.button(f"이 동 조회·판정 ({len(todo)}개 법정동)", key=f"map-run-{emd_cd}"):
        bar = st.progress(0.0, "대장 조회")
        r = run_region(
            sgg, todo, ctx.notice, ctx.ordinance, ctx.eval_date, st.session_state["raw"],
            lambda f, t: bar.progress(min(1.0, f), t),
            results_cache=st.session_state["results"], options=ctx.options, test_mode=ctx.test_mode,
        )
        bar.empty()
        st.session_state["queried"].setdefault(sgg, set()).update(b for b in todo if (sgg, b) in st.session_state["raw"])
        if r.failed_dongs:
            st.error("조회하지 못한 동이 있습니다: " + ", ".join(r.failed_dongs))
        else:
            st.rerun()


def _zoom_for(bbox: list[list[float]]) -> int:
    """경계 크기에 맞는 대략의 확대 수준(지도 폭 약 800px 기준)."""
    import math

    span = max(bbox[1][0] - bbox[0][0], bbox[1][1] - bbox[0][1], 1e-4)
    return max(7, min(17, int(math.log2(360 / span)) + 1))


def _bbox(fc: dict) -> list[list[float]] | None:
    xs, ys = [], []

    def walk(c):
        if isinstance(c[0], (int, float)):
            xs.append(c[0]), ys.append(c[1])
        else:
            for x in c:
                walk(x)

    for f in fc.get("features", []):
        walk(f["geometry"]["coordinates"])
    return [[min(ys), min(xs)], [max(ys), max(xs)]] if xs else None
