"""화면 전환 움직임: 단계(① 지역·공고 조건 → ② 후보 목록·지도 → ③ 안내문) 앞뒤 이동, 사이드바 펼침, 드롭다운·펼침 칸.

- 단계 화면은 view(): 화면이 바뀔 때만 새 컨테이너(키에 화면·방향)로 그려져, 앞으로 가면 오른쪽에서, 뒤로 가면 왼쪽에서 들어온다.
  같은 화면에서 다시 그릴 때(버튼·입력)는 키가 같아 움직이지 않는다.
- 단계 표시줄 step_bar(): 지금 단계를 표시(aria-current="step"). 단계가 바뀌면 새 칸이 진행 방향으로 채워진다.
- 움직임 줄이기 설정이면 이동 없이 투명도만 바꾼다(바뀐 사실은 그대로 보인다).
"""

from __future__ import annotations

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

/* ── 단계 표시줄 ───────────────────────────────────────────────────── */
.stepbar { display: flex; flex-wrap: wrap; align-items: center; gap: 6px 8px; margin: 14px 0 4px; padding: 0; list-style: none; font-size: .9rem; }
.stepbar li { display: flex; align-items: center; gap: 8px; }
.stepbar li + li::before { content: ""; width: 18px; height: 1px; background: currentColor; opacity: .35; }
.stepbar span { position: relative; overflow: hidden; padding: 4px 12px; border-radius: 999px;
  border: 1px solid rgba(127,127,127,.35); opacity: .75; }
.stepbar .done span { opacity: .9; }
.stepbar [aria-current="step"] span { opacity: 1; font-weight: 600; color: #fff; border-color: var(--step-on); background: var(--step-on); }
@keyframes step-fill-fwd  { from { clip-path: inset(0 100% 0 0 round 999px); } }
@keyframes step-fill-back { from { clip-path: inset(0 0 0 100% round 999px); } }
.stepbar.fwd  [aria-current="step"] span { animation: step-fill-fwd  var(--m-view) var(--m-ease) backwards; }
.stepbar.back [aria-current="step"] span { animation: step-fill-back var(--m-view) var(--m-ease) backwards; }

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
  .stepbar [aria-current="step"] span { animation: view-fade 200ms ease-out backwards !important; }
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


def _track(scope: str, view: str) -> tuple[str, int]:
    """(방향, 전환 번호). 화면이 바뀔 때만 방향을 새로 정하고 번호를 올린다(같은 화면에서 다시 그려도 그대로)."""
    allv = st.session_state.setdefault(_KEY, {})
    last = allv.get(scope)
    if last is None:
        allv[scope] = {"view": view, "dir": "none", "n": 0}
    elif last["view"] != view:
        d = "fwd" if ORDER.get(view, 0) > ORDER.get(last["view"], 0) else "back"
        allv[scope] = {"view": view, "dir": d, "n": last["n"] + 1}
    s = allv[scope]
    return s["dir"], s["n"]


def view(name: str, scope: str = "stage"):
    """단계 화면을 담는 컨테이너. scope='stage'(처음 화면 ↔ 작업 화면), 'section'(작업 화면 안 ①②③)."""
    d, n = _track(scope, name)
    return st.container(key=f"view-{scope}-{name}-{d}-{n}")


def step_bar(view_name: str, scope: str = "stage") -> None:
    """① 지역·공고 조건 → ② 후보 목록·지도 → ③ 안내문 중 지금 단계."""
    cur = STEP_OF.get(view_name, 1)
    d = (st.session_state.get(_KEY, {}).get(scope) or {}).get("dir", "none")
    items = []
    for i, label in enumerate(STEPS, 1):
        if i == cur:
            items.append(f'<li aria-current="step"><span>{i} {label}</span></li>')
        else:
            cls = ' class="done"' if i < cur else ""
            items.append(f'<li{cls}><span>{i} {label}</span></li>')
    st.markdown(f'<ol class="stepbar {d}" aria-label="진행 단계">{"".join(items)}</ol>', unsafe_allow_html=True)
