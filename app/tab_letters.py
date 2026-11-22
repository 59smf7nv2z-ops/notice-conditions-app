"""탭3 안내문 및 결과 리포트."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from app.state import Ctx
from core import letters
from core.evaluator import STATUS_LABEL
from core.llm import factory
from core.pipeline import RegionResult


def render(ctx: Ctx, res: RegionResult | None) -> None:
    st.caption(
        "수신자는 '{지번주소} 건축물 소유자(관리자)'로 씁니다. 소유자 성명·연락처는 이 시스템에 없으며, "
        "구청 내부 시스템에서 결합합니다."
    )
    if res is None or res.df.empty:
        st.info("'지역 일괄 대조' 화면에서 먼저 '조회·판정'을 누르세요.")
        return
    try:
        letters.ensure_can_generate(ctx.notice, ctx.eval_date)
    except letters.LetterBlockedError as e:
        st.warning(str(e) + " (다음 공고 대비 참고용 결과입니다)")
        return
    if ctx.notice is None:
        st.info("공고가 없어 접수기간·신청방법 등은 '(공고 확인 필요)'로 표시됩니다.")
    if ctx.test_mode:
        st.warning("시험용(다른 지역 공고) 결과입니다. 실제 발송용으로 쓰지 마세요.")

    statuses = st.multiselect(
        "발송 대상", ["CANDIDATE", "NEEDS_CHECK"], default=["CANDIDATE", "NEEDS_CHECK"], format_func=STATUS_LABEL.get
    )
    targets = res.df[res.df["status"].isin(statuses)].reset_index(drop=True)
    pins: set = st.session_state.get("letter_pins", set())
    if pins and st.checkbox(f"지도에서 추가한 건물만 ({len(pins)}건)", value=True):
        targets = targets[targets["mgmBldrgstPk"].astype(str).isin(pins)].reset_index(drop=True)
    if targets.empty:
        st.info("발송 대상이 없습니다.")
        return
    pick = pd.DataFrame(
        {
            "발송": True,
            "지번주소": targets["platPlc"],
            "상태": targets["status"].map(STATUS_LABEL),
            "경과연수": targets["age_years"],
        }
    )
    edited = st.data_editor(
        pick,
        hide_index=True,
        use_container_width=True,
        disabled=["지번주소", "상태", "경과연수"],
        column_config={"발송": st.column_config.CheckboxColumn("발송")},
        key=f"targets-{res.condition_hash}",
    )
    chosen = targets[edited["발송"].values]
    st.caption(f"선택 {len(chosen)}건 / 대상 {len(targets)}건")

    tone = st.radio("말투", list(letters.TONES), format_func=letters.TONES.get, horizontal=True)
    # 공고·말투별 1회만 LLM을 부르고 세션에 캐시. 입력은 공고 조건과 말투뿐(건물 데이터 없음)
    stt = factory.status("write")
    cache: dict = st.session_state.setdefault("templates", {})
    key = (ctx.notice.notice_id if ctx.notice else "-", ctx.notice_edited, tone, stt.name, stt.model)
    regen = st.button(
        "문구 재생성", help=f"같은 공고·말투로 틀만 다시 만듭니다({stt.label})." + (" 샘플 모드에서는 내장 틀입니다." if stt.is_mock else "")
    )
    if regen or key not in cache:
        with st.spinner("안내문 틀 만드는 중"):
            cache[key] = letters.make_template_llm(ctx.notice, tone, factory.get_provider("write"))
    template, warns, from_llm = cache[key]
    for w in warns:
        st.warning(w)
    st.caption("안내문 틀: " + ("AI가 만든 틀(빠진 항목 검사 통과)" if from_llm else "기본 틀"))
    with st.expander("틀 보기(자리표시자 포함)"):
        st.code(template, language=None)

    if chosen.empty:
        st.info("발송할 건물을 하나 이상 고르세요.")
        return
    preview = letters.fill(template, chosen.iloc[0].to_dict(), ctx.notice)
    st.markdown("**1건 미리보기**")
    st.text(preview)
    if tone == "sms":
        b = letters.sms_bytes(preview.replace(letters.REVIEW_LINE, "").strip())
        st.caption(f"문자 길이 {b}바이트 · {'SMS' if b <= letters.SMS_LIMIT_BYTES else 'LMS(90바이트 초과)'} "
                   "(검토 문구 제외 기준)")

    c1, c2 = st.columns(2)
    picked = chosen.copy()
    notice = ctx.notice
    # 파일은 버튼을 누를 때만 만든다(수백 건 docx를 매번 다시 만들지 않도록). 디스크에는 쓰지 않는다.
    c1.download_button(
        f"안내문 docx ({len(chosen)}건, 건물별 페이지)",
        lambda: letters.letters_docx(picked, template, notice),
        file_name=f"{ctx.sigungu_name}_{ctx.eval_date.strftime('%Y%m%d')}_안내문_{letters.TONES[tone]}.docx",
        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        on_click="ignore",
    )
    c2.download_button(
        "대상 목록 CSV",
        lambda: letters.targets_csv(picked),
        file_name=f"{ctx.sigungu_name}_{ctx.eval_date.strftime('%Y%m%d')}_안내대상.csv",
        mime="text/csv",
        on_click="ignore",
    )
