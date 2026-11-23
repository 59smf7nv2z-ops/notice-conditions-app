"""화면 전환 움직임: 단계(① 지역·공고 조건 → ② 후보 목록·지도 → ③ 안내문) 앞뒤 이동, 사이드바 펼침, 드롭다운·펼침 칸.

- 단계 화면은 view(): 화면이 바뀔 때만 새 컨테이너(키에 화면·방향)로 그려져, 앞으로 가면 오른쪽에서, 뒤로 가면 왼쪽에서 들어온다.
  같은 화면에서 다시 그릴 때(버튼·입력)는 키가 같아 움직이지 않는다.
- 단계 표시줄 step_bar(): 단계 버튼. 누르면 그 단계로 가고(갈 수 없는 단계는 꺼 둠), 단계가 바뀌면 새 칸이 진행 방향으로 채워진다.
- 움직임 줄이기 설정이면 이동 없이 투명도만 바꾼다(바뀐 사실은 그대로 보인다).
"""

from __future__ import annotations

import html

import streamlit as st

ORDER = {"home": 0, "work": 1, "region": 1, "map": 2, "letters": 3}  # 앞뒤 방향을 정하는 순서
STEP_OF = {"home": 1, "region": 2, "map": 2, "letters": 3}
STEPS = ("지역·공고 조건", "후보 목록·지도", "안내문")
_KEY = "_motion"  # {scope: {"view", "dir", "n"}}

CSS = """
<style>
:root {
  --m-ease: cubic-bezier(.16, 1, .3, 1);     /* 빠르게 도착해 부드럽게 멈춤 */
  --m-exit: cubic-bezier(.4, 0, 1, 1);
  --m-view: 380ms;                            /* 단계 전환 */
  --m-panel: 260ms;                           /* 사이드바·펼침 칸 */
  --m-pop: 160ms;                             /* 드롭다운 */
  --step-on: __PRIMARY__;
}

/* ── 단계 전환: 앞으로 → 오른쪽에서, 뒤로 → 왼쪽에서 ─────────────────── */
@keyframes view-fwd  { from { opacity: 0; transform: translateX(28px); } }
@keyframes view-back { from { opacity: 0; transform: translateX(-28px); } }
@keyframes view-fade { from { opacity: 0; } }
[class*="st-key-view-"][class*="-fwd-"]  { animation: view-fwd  var(--m-view) var(--m-ease) backwards; }
[class*="st-key-view-"][class*="-back-"] { animation: view-back var(--m-view) var(--m-ease) backwards; }
[class*="st-key-view-"][class*="-none-"] { animation: view-fade 200ms ease-out backwards; }

/* ── 단계 표시줄: 누르면 그 단계로 간다. 지금 단계는 채운 알약, 바뀌면 진행 방향으로 채워진다 ── */
[class*="st-key-stepnav-"] { align-items: center; gap: 6px 8px !important; margin: 14px 0 4px; }
[class*="st-key-stepnav-"] [class*="st-key-step-"] { width: auto !important; flex: 0 0 auto; display: flex; align-items: center; gap: 8px; }
[class*="st-key-stepnav-"] [class*="st-key-step-"]:not([class*="st-key-step-1"])::before {
  content: ""; width: 18px; height: 1px; background: currentColor; opacity: .35; }
[class*="st-key-stepnav-"] button { border-radius: 999px; min-height: 0; padding: 4px 12px; }
[class*="st-key-stepnav-"] button p { font-size: .9rem; }
[class*="st-key-stepnav-"] [class*="-cur"] button p { font-weight: 600; }
@keyframes step-fill-fwd  { from { clip-path: inset(0 100% 0 0 round 999px); } }
@keyframes step-fill-back { from { clip-path: inset(0 0 0 100% round 999px); } }
[class*="st-key-stepnav-fwd-"]  [class*="-cur"] button { animation: step-fill-fwd  var(--m-view) var(--m-ease) backwards; }
[class*="st-key-stepnav-back-"] [class*="-cur"] button { animation: step-fill-back var(--m-view) var(--m-ease) backwards; }
.sr-only { position: absolute; width: 1px; height: 1px; margin: -1px; padding: 0; overflow: hidden; clip-path: inset(50%); white-space: nowrap; border: 0; }

/* ── 지역 제목: 구 › 동. 동이 바뀌면 동 이름만 왼쪽에서 밀려 들어온다 ──── */
.crumb-sep { margin: 0 .1em; opacity: .4; font-weight: 400; }
.crumb-dong { display: inline-block; }
.crumb-dong.none { opacity: .55; font-weight: 400; font-size: .8em; }
@keyframes crumb-in { from { opacity: 0; transform: translateX(-10px); filter: blur(2px); } }
@keyframes crumb-sep-in { from { opacity: 0; } }
[class*="st-key-crumb-"]:not(.st-key-crumb-0) .crumb-dong { animation: crumb-in 320ms var(--m-ease) 60ms backwards; }
[class*="st-key-crumb-"]:not(.st-key-crumb-0) .crumb-sep { animation: crumb-sep-in 200ms ease-out backwards; }

/* ── 사이드바: 펼치면 내용이 패널을 따라 들어온다 ────────────────────── */
[data-testid="stSidebar"] { transition-timing-function: var(--m-ease) !important; }
[data-testid="stSidebar"] [data-testid="stSidebarUserContent"] {
  transition: opacity var(--m-panel) var(--m-ease) 60ms, transform var(--m-panel) var(--m-ease) 60ms;
}
[data-testid="stSidebar"][data-collapsed="true"] [data-testid="stSidebarUserContent"] {
  opacity: 0; transform: translateX(-16px); transition-duration: 120ms; transition-delay: 0ms; transition-timing-function: var(--m-exit);
}

/* ── 드롭다운(선택 상자·여러 개 고르기·날짜): 붙은 자리에서 펼쳐진다 ─────── */
@keyframes pop-in { from { opacity: 0; transform: translateY(-6px) scale(.98); } }
div[data-baseweb="popover"] > div { animation: pop-in var(--m-pop) var(--m-ease) backwards; transform-origin: top center; }

/* ── 펼침 칸(expander): 열면 내용이 위에서 드러난다 ─────────────────── */
@keyframes reveal-down { from { opacity: 0; transform: translateY(-6px); clip-path: inset(0 0 100% 0); } }
details[open] > [data-testid="stExpanderDetails"] { animation: reveal-down var(--m-panel) var(--m-ease) backwards; }
details > summary [data-testid="stExpanderIcon"] { transition: transform var(--m-panel) var(--m-ease); }

/* ── 실행 중 표시: 달리는 사람 그림 대신 회전 원 ─────────────────────── */
[data-testid="stStatusWidgetRunningManIcon"] { display: none !important; }
[data-testid="stStatusWidget"] :has(> [data-testid="stStatusWidgetRunningManIcon"])::before {
  content: ""; width: 1rem; height: 1rem; margin-right: .5rem; display: inline-block; vertical-align: middle;
  border: 2px solid currentColor; border-right-color: transparent; border-radius: 50%; opacity: .6;
  animation: m-spin .8s linear infinite;
}
@keyframes m-spin { to { transform: rotate(360deg); } }

/* ── 움직임 줄이기: 이동은 없애고 투명도 변화만 남긴다 ───────────────── */
@media (prefers-reduced-motion: reduce) {
  [class*="st-key-view-"] { animation: view-fade 200ms ease-out backwards !important; }
  [class*="st-key-stepnav-"] [class*="-cur"] button { animation: view-fade 200ms ease-out backwards !important; }
  [class*="st-key-crumb-"] .crumb-dong { animation-name: crumb-sep-in !important; }
  [data-testid="stSidebar"][data-collapsed="true"] [data-testid="stSidebarUserContent"] { transform: none; }
  [data-testid="stSidebar"] [data-testid="stSidebarUserContent"] { transition-property: opacity; }
  div[data-baseweb="popover"] > div, details[open] > [data-testid="stExpanderDetails"] { animation: view-fade 120ms ease-out backwards; }
  [data-testid="stStatusWidget"] :has(> [data-testid="stStatusWidgetRunningManIcon"])::before { animation-duration: 2.4s; }
}
</style>
"""


def inject() -> None:
    primary = st.get_option("theme.primaryColor") or "#c8323a"
    st.markdown(CSS.replace("__PRIMARY__", primary), unsafe_allow_html=True)


def _track(scope: str, view, rank=ORDER.get) -> tuple[str, int]:
    """(방향, 전환 번호). 화면이 바뀔 때만 방향을 새로 정하고 번호를 올린다(같은 화면에서 다시 그려도 그대로)."""
    allv = st.session_state.setdefault(_KEY, {})
    last = allv.get(scope)
    if last is None:
        allv[scope] = {"view": view, "dir": "none", "n": 0}
    elif last["view"] != view:
        d = "fwd" if (rank(view) or 0) > (rank(last["view"]) or 0) else "back"
        allv[scope] = {"view": view, "dir": d, "n": last["n"] + 1}
    s = allv[scope]
    return s["dir"], s["n"]


def view(name: str, scope: str = "stage"):
    """단계 화면을 담는 컨테이너. scope='stage'(처음 화면 ↔ 작업 화면), 'section'(작업 화면 안 ①②③)."""
    d, n = _track(scope, name)
    return st.container(key=f"view-{scope}-{name}-{d}-{n}")


def step_bar(view_name: str, nav: dict | None = None) -> None:
    """① 지역·공고 조건 → ② 후보 목록·지도 → ③ 안내문. nav={단계 번호: 누르면 부를 함수}, 없는 단계는 꺼 둔다.
    단계 번호가 바뀔 때만 다시 채워진다(② 안에서 지역 일괄 대조 ↔ 지도는 그대로)."""
    cur = STEP_OF.get(view_name, 1)
    d, n = _track("steps", cur, rank=int)
    nav = nav or {}
    st.markdown(f'<p class="sr-only">지금 단계: {cur} {STEPS[cur - 1]}</p>', unsafe_allow_html=True)
    with st.container(horizontal=True, key=f"stepnav-{d}-{n}"):
        for i, label in enumerate(STEPS, 1):
            here = i == cur
            st.button(
                f"{i} {label}",
                key=f"step-{i}-cur" if here else f"step-{i}",
                type="primary" if here else "secondary",
                on_click=None if here else nav.get(i),
                disabled=not here and i not in nav,
            )


def region_heading(region: str, dong: str) -> None:
    """'충청북도 청주시 상당구 › 용암동'. 동이 바뀔 때만 새 컨테이너로 그려 동 이름이 다시 들어온다(처음 그릴 때는 움직이지 않음)."""
    allv = st.session_state.setdefault(_KEY, {})
    last = allv.get("crumb")
    if last is None:
        allv["crumb"] = last = {"label": (region, dong), "n": 0}
    elif last["label"] != (region, dong):
        last.update(label=(region, dong), n=last["n"] + 1)
    shown = html.escape(dong) if dong else "동을 고르세요"
    cls = "crumb-dong" if dong else "crumb-dong none"
    with st.container(key=f"crumb-{last['n']}"):
        st.markdown(
            f'### {html.escape(region)} <span class="crumb-sep" aria-hidden="true">›</span> '
            f'<span class="{cls}">{shown}</span>',
            unsafe_allow_html=True,
        )

