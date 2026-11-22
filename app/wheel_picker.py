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
/* 아직 안 고름: 고른 값(진하고 굵게)보다 옅지만 읽을 수 있게(대비 4.5:1 이상) */
.wp-item.ph, .wp-item.ph[aria-selected="true"] {{ opacity: .72; font-weight: 400; }}
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

  if (rebuilt) root._marked = -1;
  const mark = (i) => {{   // 스크롤 중 매 프레임 불리므로 칸이 바뀔 때만 손댄다
    if (root._marked === i) return;
    const prev = list.children[root._marked], li = list.children[i];
    if (prev) prev.setAttribute('aria-selected', 'false');
    if (li) {{ li.setAttribute('aria-selected', 'true'); list.setAttribute('aria-activedescendant', li.id); }}
    root._marked = i;
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
  // 멈추자마자 보내지 않는다: 잠깐 더 기다려 지나가는 칸마다 앱을 다시 그리지 않게 한다.
  // 마우스·터치는 0.25초, 키보드는 0.5초(화살표를 이어 누르는 사이). Enter나 초점이 빠지면 바로 보낸다.
  let wait = null, viaKey = false, dragging = false;
  const settle = () => {{ clearTimeout(wait); wait = setTimeout(() => {{ wait = null; if (!dragging) commit(); }}, viaKey ? 500 : 250); }};
  const flush = () => {{ if (wait !== null) {{ clearTimeout(wait); wait = null; commit(); }} }};
  list.addEventListener('focusout', flush);

  sel.addEventListener('change', () => {{
    const i = root._items.findIndex(it => String(it.v) === sel.value);
    if (i >= 0) send(i);
  }});

  // 스크롤이 멈추면 고른다(scrollend가 없으면 잠깐 멈춤으로 판단)
  let t;
  list.addEventListener('scroll', () => {{
    mark(Math.round(list.scrollTop / H));
    clearTimeout(wait);   // 아직 움직이는 중
    if (!('onscrollend' in window)) {{ clearTimeout(t); t = setTimeout(() => {{ if (!dragging) settle(); }}, 120); }}
  }}, {{ passive: true }});
  list.addEventListener('scrollend', () => {{ if (!dragging) settle(); }});

  // 페이지 스크롤을 가로채지 않는다: 휠은 초점을 받았거나, 마우스를 잠시 올려 둔 뒤에만 돌린다.
  // 페이지를 굴리던 중 마우스가 휠 위로 지나가면 그 입력은 페이지로 넘긴다. 첫·끝 항목에서 더 굴려도 페이지로.
  let hoverAt = Infinity, pageAt = 0;
  list.addEventListener('pointerenter', (e) => {{ if (e.pointerType === 'mouse') hoverAt = performance.now(); }});
  list.addEventListener('pointerleave', () => {{ hoverAt = Infinity; }});
  document.addEventListener('scroll', (e) => {{ if (e.target !== list) pageAt = performance.now(); }}, {{ capture: true, passive: true }});
  const scroller = () => {{
    for (let n = root.getRootNode().host || root; n; n = n.parentElement || (n.getRootNode && n.getRootNode().host)) {{
      if (n === document.body || n === document.documentElement) break;
      const oy = getComputedStyle(n).overflowY;
      if ((oy === 'auto' || oy === 'scroll') && n.scrollHeight > n.clientHeight) return n;
    }}
    return document.scrollingElement;
  }};
  const owns = (e) => {{
    const now = performance.now();
    if (root.getRootNode().activeElement === list) return true;        // 키보드 초점을 받은 휠
    return now - hoverAt > 400 && now - pageAt > 400;                   // 잠시 머문 마우스 + 페이지가 막 구르던 중이 아님
  }};
  const toPage = (e) => {{
    const k = e.deltaMode === 1 ? 16 : e.deltaMode === 2 ? innerHeight : 1;
    scroller().scrollBy({{ top: e.deltaY * k, left: e.deltaX * k }});
  }};

  // 마우스 휠: 눈금 하나 = 한 칸. 트랙패드(작은 값이 잇달아 옴)는 한 칸 높이만큼 쌓일 때마다 한 칸
  let acc = 0, target = null, idle;
  list.addEventListener('wheel', (e) => {{
    viaKey = false;
    e.preventDefault();   // 휠 목록이 직접 구르면 스냅이 어긋나므로 항상 막고, 페이지 몫이면 페이지를 대신 굴린다
    const at = target ?? Math.round(list.scrollTop / H);
    const edge = (e.deltaY < 0 && at <= 0) || (e.deltaY > 0 && at >= root._items.length - 1);
    if (Math.abs(e.deltaX) > Math.abs(e.deltaY) || !owns(e) || (edge && target === null)) {{ toPage(e); return; }}
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
    viaKey = false;
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

  // 창을 벗어나면 끌던 상태를 푼다
  window.addEventListener('blur', end);

  // 글자로 건너뛰기: '수'·'수원' 또는 초성 'ㅅ'·'ㅅㅇ'. 한/영 전환 없이 영문 자판으로 쳐도(t → ㅅ) 찾는다.
  // 0.6초 안에 이어 친 글자는 한 단어로 본다. 같은 글자를 거듭 치면 그 글자로 시작하는 다음 항목으로.
  const CHO = 'ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎ';
  const KO = {{ q:'ㅂ', w:'ㅈ', e:'ㄷ', r:'ㄱ', t:'ㅅ', a:'ㅁ', s:'ㄴ', d:'ㅇ', f:'ㄹ', g:'ㅎ', z:'ㅋ', x:'ㅌ', c:'ㅊ', v:'ㅍ',
               Q:'ㅃ', W:'ㅉ', E:'ㄸ', R:'ㄲ', T:'ㅆ' }};
  const cho = (c) => {{ const n = c.charCodeAt(0) - 0xAC00; return n >= 0 && n < 11172 ? CHO[Math.floor(n / 588)] : c; }};
  const fits = (text, q) => {{
    const t = text.replace(/^[^0-9A-Za-z가-힣]+/, '').toLowerCase();
    if (t.length < q.length) return false;
    for (let j = 0; j < q.length; j++) {{
      const a = t[j], b = q[j];
      if (a !== b && !(CHO.includes(b) && cho(a) === b)) return false;
    }}
    return true;
  }};
  let typed = '', typedAt = 0;
  const jump = (ch) => {{
    const now = performance.now();
    typed = now - typedAt < 600 ? typed + ch : ch;
    typedAt = now;
    const items = root._items, cur = Math.round(list.scrollTop / H);
    const same = typed.length > 1 && [...typed].every(c => c === typed[0]);
    const q = same ? typed[0] : typed;
    const from = same || typed.length === 1 ? cur + 1 : cur;   // 한 글자: 다음 후보로, 이어 치기: 지금 자리부터
    for (let k = 0; k < items.length; k++) {{
      const i = (from + k) % items.length;
      if (items[i].v >= 0 && fits(items[i].t, q)) return go(i, true);
    }}
    return null;
  }};

  // 키보드
  list.addEventListener('keydown', (e) => {{
    const cur = Math.round(list.scrollTop / H);
    const to = {{ ArrowDown: cur + 1, ArrowUp: cur - 1, PageDown: cur + 4, PageUp: cur - 4, Home: 0, End: root._items.length - 1 }}[e.key];
    if (e.key === 'Enter') {{ clearTimeout(wait); wait = null; commit(); return; }}
    viaKey = true;
    if (to !== undefined) {{ e.preventDefault(); go(to, true); return; }}
    if (e.ctrlKey || e.metaKey || e.altKey || e.isComposing || e.key.length !== 1) return;
    if (e.key === ' ' && !typed) return;
    e.preventDefault();
    const ch = e.key.toLowerCase();
    const keep = typed, keepAt = typedAt;
    if (jump(ch) === null && KO[e.key]) {{ typed = keep; typedAt = keepAt; jump(KO[e.key]); }}   // 영문 자판으로 친 한글
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
