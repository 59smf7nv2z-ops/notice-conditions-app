"""iOS UIPickerView 같은 휠 선택기(Streamlit components v2, 빌드 없이 HTML·CSS·JS).

데스크톱(마우스·트랙패드)
- 스크롤: scroll-snap-type: y mandatory. 멈추면 가장 가까운 항목이 가운데 선택 띠에 맞춰진다.
- 모양: 가운데 선택 띠만 강조, 위아래로 멀어지는 항목은 mask-image 그라데이션으로 흐려진다.
- 입력: 마우스 끌기, 마우스 휠(눈금 하나 = 한 칸), 항목 클릭, 키보드(↑↓·Home·End·PageUp/Down).
휴대폰·태블릿(터치가 주 입력: hover 없음 + pointer coarse)
- 표준 <select>/<option>으로 그린다. iOS는 아래에서 네이티브 휠(UIPickerView), 안드로이드는 네이티브 선택 창이 올라온다.

값은 Python이 기준이다. 고른 값은 한 번만 Python으로 보낸다(trigger 'pick').
wheel_select()는 st.selectbox처럼 쓰고 값은 session_state[key]에 둔다(밖에서 그 값을 바꾸면 휠이 그 항목으로 굴러간다).
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from contextlib import nullcontext
from typing import Any

import streamlit as st

ITEM_H = 36   # 항목 높이(px)
NOTHING = object()  # 이번 실행에서 고르지 않음

CSS = f"""
:host {{ display: block; }}
*, *::before, *::after {{ box-sizing: border-box; }}
.wp {{ --ease: cubic-bezier(.16, 1, .3, 1); --pc: var(--st-primary-color, #c8323a);
  font-family: var(--st-font, "Source Sans Pro", sans-serif); color: var(--st-text-color, inherit); }}
.wp-label {{ font-size: .875rem; margin: 0 0 6px; opacity: .85; }}
.wp-frame {{
  position: relative; height: calc({ITEM_H}px * var(--rows, 5)); border-radius: 12px; overflow: hidden;
  background: var(--st-secondary-background-color, rgba(127,127,127,.08));
}}
/* 가운데 선택 띠: 항목 뒤에 깔린다 */
.wp-band {{
  position: absolute; left: 6px; right: 6px; top: calc(50% - {ITEM_H / 2}px); height: {ITEM_H}px;
  border-radius: 8px; pointer-events: none;
  background: color-mix(in srgb, var(--pc) 14%, transparent);
  border: 1px solid color-mix(in srgb, var(--pc) 45%, transparent);
}}
.wp-list {{
  position: relative; height: 100%; margin: 0; list-style: none;
  padding: calc({ITEM_H}px * (var(--rows, 5) - 1) / 2) 0;
  overflow-y: scroll; overscroll-behavior: contain; scrollbar-width: none;
  scroll-snap-type: y mandatory; touch-action: pan-y; outline: none; cursor: grab;
  -webkit-mask-image: linear-gradient(to bottom, transparent, rgba(0,0,0,.45) 18%, #000 calc(50% - {ITEM_H / 2}px), #000 calc(50% + {ITEM_H / 2}px), rgba(0,0,0,.45) 82%, transparent);
          mask-image: linear-gradient(to bottom, transparent, rgba(0,0,0,.45) 18%, #000 calc(50% - {ITEM_H / 2}px), #000 calc(50% + {ITEM_H / 2}px), rgba(0,0,0,.45) 82%, transparent);
}}
.wp-list::-webkit-scrollbar {{ display: none; }}
.wp-list.dragging {{ scroll-snap-type: none; cursor: grabbing; user-select: none; }}
.wp-ring {{ position: absolute; inset: 0; border-radius: 12px; pointer-events: none; opacity: 0;
  box-shadow: inset 0 0 0 2px var(--pc); }}
.wp-list:focus-visible + .wp-ring {{ opacity: 1; }}
.wp-item {{
  height: {ITEM_H}px; line-height: {ITEM_H}px; padding: 0 10px; text-align: center;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  scroll-snap-align: center; scroll-snap-stop: always;
  font-size: var(--fs, 1rem); opacity: .7; transition: opacity 150ms ease;
}}
.wp-item[aria-selected="true"] {{ opacity: 1; font-weight: 600; }}
.wp-item.ph {{ opacity: .45; }}
.wp.off .wp-frame, .wp.off .wp-native {{ opacity: .45; pointer-events: none; }}

/* 휴대폰: 표준 select(운영체제 기본 선택 창) */
.wp-native {{ display: none; position: relative; }}
.wp.native .wp-frame {{ display: none; }}
.wp.native .wp-native {{ display: block; }}
.wp-native select {{
  width: 100%; height: 44px; padding: 0 40px 0 12px; border-radius: 8px; appearance: none; -webkit-appearance: none;
  font: inherit; font-size: 16px; /* 16px 미만이면 iOS가 확대한다 */ color: inherit;
  background: var(--st-secondary-background-color, rgba(127,127,127,.08));
  border: 1px solid color-mix(in srgb, currentColor 18%, transparent);
}}
.wp-native select:focus-visible {{ outline: 2px solid var(--pc); outline-offset: 1px; }}
.wp-native::after {{ content: ""; position: absolute; right: 16px; top: 50%; width: 8px; height: 8px; pointer-events: none;
  border-right: 2px solid currentColor; border-bottom: 2px solid currentColor; opacity: .6; transform: translateY(-70%) rotate(45deg); }}

/* 다음 단계 휠이 처음 나타날 때: 옆에서 스윽 미끄러져 서서히 드러난다 */
@keyframes wp-reveal {{
  from {{ opacity: 0; transform: translateX(-22px); clip-path: inset(0 100% 0 0 round 12px); }}
  60%  {{ clip-path: inset(0 0 0 0 round 12px); }}
}}
@keyframes wp-fade {{ from {{ opacity: 0; }} }}
.wp.reveal {{ animation: wp-reveal 460ms var(--ease) backwards; }}
@media (prefers-reduced-motion: reduce) {{
  .wp.reveal {{ animation: wp-fade 200ms ease-out backwards; }}
  .wp-item {{ transition: none; }}
}}
"""

HTML = (
    '<div class="wp"><div class="wp-label"></div>'
    '<div class="wp-frame"><div class="wp-band"></div><ul class="wp-list" role="listbox" tabindex="0"></ul><div class="wp-ring"></div></div>'
    '<div class="wp-native"><select></select></div></div>'
)

JS = f"""
const H = {ITEM_H};
const touchFirst = () => matchMedia('(hover: none) and (pointer: coarse)').matches;
export default function (component) {{
  const {{ data, parentElement, setTriggerValue }} = component;
  const root = parentElement.querySelector('.wp');
  const list = root.querySelector('.wp-list');
  const sel = root.querySelector('.wp-native select');
  root._set = setTriggerValue;           // 매번 최신 함수로
  const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;
  const native = data.native === 'always' || (data.native === 'auto' && touchFirst());

  root.classList.toggle('native', native);
  root.classList.toggle('off', !!data.disabled);
  if (data.reveal && !root._revealed) {{ root._revealed = true; root.classList.add('reveal'); }}
  root.style.setProperty('--rows', data.rows);
  if (data.fs) root.style.setProperty('--fs', data.fs);
  const lab = root.querySelector('.wp-label');
  lab.textContent = data.label;
  lab.hidden = !data.label;
  list.setAttribute('aria-label', data.label);
  sel.setAttribute('aria-label', data.label);
  list.setAttribute('aria-disabled', data.disabled ? 'true' : 'false');
  list.tabIndex = data.disabled ? -1 : 0;
  sel.disabled = !!data.disabled;

  // ── 항목: 목록이 바뀔 때만 다시 만든다 ──
  const sig = JSON.stringify(data.items);
  const rebuilt = root._sig !== sig;
  if (rebuilt) {{
    root._sig = sig;
    list.replaceChildren(...data.items.map((it, i) => {{
      const li = document.createElement('li');
      li.className = 'wp-item' + (it.v < 0 ? ' ph' : '');
      li.id = `wp-${{data.key}}-${{i}}`;
      li.setAttribute('role', 'option');
      li.dataset.i = i;
      li.title = it.t;
      li.textContent = it.t;
      return li;
    }}));
    sel.replaceChildren(...data.items.map((it) => {{
      const o = document.createElement('option');
      o.value = it.v; o.textContent = it.t;
      return o;
    }}));
  }}
  root._items = data.items;
  const want = Math.max(0, data.items.findIndex(it => it.v === data.value));
  if (data.items[want]) sel.value = String(data.items[want].v);

  const mark = (i) => {{
    list.querySelectorAll('.wp-item').forEach((li, k) => li.setAttribute('aria-selected', k === i ? 'true' : 'false'));
    const li = list.children[i];
    if (li) list.setAttribute('aria-activedescendant', li.id);
  }};
  const go = (i, smooth) => {{
    i = Math.max(0, Math.min(root._items.length - 1, i));
    list.scrollTo({{ top: i * H, behavior: smooth && !reduce ? 'smooth' : 'auto' }});
    mark(i);
    return i;
  }};
  root._go = go;

  // 처음이거나 Python이 값을 바꿨으면(검색·공고 지역) 그 항목으로
  if (rebuilt || root._want !== want) {{
    root._want = want;
    root._committed = want;
    if (!native) requestAnimationFrame(() => go(want, !rebuilt));
  }}

  if (root._wired) return;   // 이벤트는 한 번만 붙인다
  root._wired = true;

  const send = (i) => {{
    if (i !== root._committed && root._items[i]) {{ root._committed = i; root._set('pick', root._items[i].v); }}
  }};
  const commit = () => {{ const i = Math.round(list.scrollTop / H); mark(i); send(i); }};

  sel.addEventListener('change', () => {{
    const i = root._items.findIndex(it => String(it.v) === sel.value);
    if (i >= 0) send(i);
  }});

  // 스크롤이 멈추면 고른다(scrollend가 없으면 잠깐 멈춤으로 판단)
  let t, dragging = false;
  list.addEventListener('scroll', () => {{
    mark(Math.round(list.scrollTop / H));
    if (!('onscrollend' in window)) {{ clearTimeout(t); t = setTimeout(() => {{ if (!dragging) commit(); }}, 120); }}
  }}, {{ passive: true }});
  list.addEventListener('scrollend', () => {{ if (!dragging) commit(); }});

  // 마우스 휠: 눈금 하나 = 한 칸. 트랙패드(작은 값이 잇달아 옴)는 한 칸 높이만큼 쌓일 때마다 한 칸
  let acc = 0, target = null, idle;
  list.addEventListener('wheel', (e) => {{
    e.preventDefault();
    clearTimeout(idle); idle = setTimeout(() => {{ acc = 0; target = null; }}, 180);
    let step = 0;
    if (e.deltaMode !== 0 || Math.abs(e.deltaY) >= 50) step = Math.sign(e.deltaY);
    else {{ acc += e.deltaY; step = Math.trunc(acc / H); acc -= step * H; }}
    if (!step) return;
    target = go((target ?? Math.round(list.scrollTop / H)) + step, true);
  }}, {{ passive: false }});

  // 마우스로 끌기(터치는 기본 스크롤 + scroll-snap)
  let y0 = 0, top0 = 0, moved = 0, downItem = null;
  list.addEventListener('pointerdown', (e) => {{
    if (e.pointerType !== 'mouse' || e.button !== 0) return;
    dragging = true; moved = 0; y0 = e.clientY; top0 = list.scrollTop;
    downItem = e.target.closest ? e.target.closest('.wp-item') : null;  // 포인터를 잡으면 놓을 때 대상이 목록이 되므로 미리 기억
    list.setPointerCapture(e.pointerId);
  }});
  list.addEventListener('pointermove', (e) => {{
    if (!dragging) return;
    const dy = e.clientY - y0; moved = Math.max(moved, Math.abs(dy));
    if (moved > 3) list.classList.add('dragging');
    list.scrollTop = top0 - dy;
  }});
  const end = () => {{
    if (!dragging) return;
    dragging = false;
    list.classList.remove('dragging');
    if (moved <= 3) {{ if (downItem) go(+downItem.dataset.i, true); }}   // 끌지 않았으면 클릭: 누른 항목으로
    else go(Math.round(list.scrollTop / H), true);
    downItem = null;
  }};
  list.addEventListener('pointerup', end);
  list.addEventListener('pointercancel', end);
  list.addEventListener('lostpointercapture', end);

  // 펜·터치 화면 노트북 등에서 항목을 톡 누르면 그 항목으로
  list.addEventListener('click', (e) => {{
    if (e.pointerType === 'mouse') return;
    const li = e.target.closest('.wp-item');
    if (li) go(+li.dataset.i, true);
  }});

  // 키보드
  list.addEventListener('keydown', (e) => {{
    const cur = Math.round(list.scrollTop / H);
    const to = {{ ArrowDown: cur + 1, ArrowUp: cur - 1, PageDown: cur + 4, PageUp: cur - 4, Home: 0, End: root._items.length - 1 }}[e.key];
    if (to === undefined) return;
    e.preventDefault();
    go(to, true);
  }});
}}
"""

_wheel = st.components.v2.component("wheel_picker", html=HTML, css=CSS, js=JS)


def wheel(
    label: str,
    options: Sequence[Any],
    value: Any,
    *,
    key: str,
    format_func: Callable[[Any], str] = str,
    disabled: bool = False,
    placeholder: str | None = "고르세요",
    rows: int = 5,
    reveal: bool = False,
    font_size: str | None = None,
    native: str = "auto",
) -> Any:
    """휠 하나. 이번 실행에서 사용자가 고른 값을 돌려준다(고르지 않았으면 NOTHING, 자리 표시를 고르면 None).

    placeholder가 있으면 맨 위에 늘 둔다: 고른 값은 휠이 그려진 뒤에 Python에 오므로, 항목 자리가 바뀌지 않아야 휠이 튀지 않는다.
    reveal: 처음 나타날 때 옆에서 미끄러져 드러난다. native: 'auto'(터치 기기면 운영체제 선택 창), 'never', 'always'.
    """
    opts = list(options)
    idx = opts.index(value) if value in opts else -1
    items = ([{"v": -1, "t": placeholder}] if placeholder is not None else []) + \
        ([] if disabled else [{"v": i, "t": format_func(o)} for i, o in enumerate(opts)])
    ckey = re.sub(r"_{2,}", "_", key)  # 컴포넌트 키에는 '__'를 쓸 수 없다(공고 ID에 들어 있을 수 있음)
    res = _wheel(
        key=ckey,
        data={"label": label, "items": items, "value": idx, "disabled": disabled, "key": ckey, "rows": rows,
              "reveal": reveal, "fs": font_size, "native": native},
        on_pick_change=lambda: None,
    )
    pick = getattr(res, "pick", None) if res is not None else None
    if pick is None:
        return NOTHING
    return None if pick < 0 else opts[pick] if pick < len(opts) else NOTHING


def wheel_select(
    container,
    label: str,
    options: Sequence[Any],
    *,
    key: str,
    index: int = 0,
    format_func: Callable[[Any], str] = str,
    rows: int = 3,
    font_size: str | None = None,
) -> Any:
    """st.selectbox 대신 쓰는 휠(값이 늘 하나 있음). 값은 session_state[key]에 둔다(없거나 목록에 없으면 index 항목)."""
    opts = list(options)
    ss = st.session_state
    if ss.get(key) not in opts:
        ss[key] = opts[index] if opts else None
    with nullcontext() if container is None or container is st else container:
        got = wheel(label, opts, ss.get(key), key=f"{key}-wheel", format_func=format_func, placeholder=None,
                    rows=rows, font_size=font_size)
    if got is not NOTHING and got is not None:
        ss[key] = got
    return ss.get(key)
