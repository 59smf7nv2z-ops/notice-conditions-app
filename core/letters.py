"""소유자 안내문 (틀 + 자리표시자).

- 공고·말투별 틀 1개를 만들고, 코드가 건물마다 자리표시자를 채운다.
  LLM에는 건물 단위 데이터(주소, 대장 행)를 보내지 않는다(단계 6에서 틀만 LLM으로 만든다).
- 내장 틀 3종(어르신 맞춤형 / 공식 행정문서형 / 알림톡·SMS형). LLM 없이도 동작한다.
- 틀 검증: 허용 목록 밖 자리표시자 금지, 틀 안에 직접 쓴 수치(숫자+㎡/년/층 등) 금지, 확정 표현 금지,
  마지막 줄 '발송 전 담당자 검토'.
- 수신자는 '{지번주소} 건축물 소유자(관리자)'. 소유자 성명·연락처는 이 시스템에 없다.
"""

from __future__ import annotations

import io
import re
from datetime import date

import pandas as pd
from docx import Document
from docx.enum.text import WD_BREAK
from docx.oxml.ns import qn
from docx.shared import Pt

from core.conditions import NoticeConditions
from core.evaluator import CANDIDATE, NEEDS_CHECK

TONES = {"elder": "어르신 맞춤형", "official": "공식 행정문서형", "sms": "알림톡·SMS형"}

# 계획서의 자리표시자 13개 + 공고 단위 값 2개(사업명, 발신기관) + 상태별 안내 문구(판정안내)
BUILDING_PLACEHOLDERS = ("지번주소", "도로명주소", "사용승인일", "경과연수", "주구조", "주용도", "지상층수", "연면적")
NOTICE_PLACEHOLDERS = ("접수기간", "신청방법", "접수처", "문의처", "제출서류", "사업명", "발신기관")
STATUS_PLACEHOLDER = "판정안내"
ALLOWED = set(BUILDING_PLACEHOLDERS) | set(NOTICE_PLACEHOLDERS) | {STATUS_PLACEHOLDER}

STATUS_PHRASE = {
    CANDIDATE: "지원 대상에 해당할 가능성이 높습니다",
    NEEDS_CHECK: "지원 대상에 해당할 수 있습니다",
}
REVIEW_LINE = "※ 이 안내문은 시스템 초안입니다. 발송 전 담당자 검토가 필요합니다."
SMS_LIMIT_BYTES = 90
MISSING = "(공고 확인 필요)"

_PLACEHOLDER_RE = re.compile(r"\{([^{}]*)\}")
_NUMBER_UNIT_RE = re.compile(r"\d[\d,.]*\s*(㎡|m²|m2|제곱미터|평|년|층|세대|가구|원|%|개소)")
_ASSERTIVE = ("선정되었습니다", "선정 대상입니다", "지원 대상입니다", "확정되었습니다", "반드시 지원")

BUILTIN: dict[str, str] = {
    "elder": """{발신기관}에서 알려 드립니다

수신: {지번주소} 건축물 소유자(관리자)님

안녕하세요. 오래된 건물이 안전한지 무료로 살펴보는 「{사업명}」을 안내해 드립니다.

건축물대장을 살펴보니 이 건물은 {판정안내}.
- 주소: {지번주소} ({도로명주소})
- 사용승인일: {사용승인일} (지은 지 {경과연수})
- 구조·용도: {주구조}, {주용도}
- 층수·면적: 지상 {지상층수}, 연면적 {연면적}

신청 기간: {접수기간}
신청 방법: {신청방법}
접수하는 곳: {접수처}
준비할 서류: {제출서류}
궁금하신 점은 {문의처}로 편하게 전화 주세요.

최종 지원 여부는 신청 후 현장 확인과 심사를 거쳐 정해집니다.
""" + REVIEW_LINE,
    "official": """{발신기관}

수신: {지번주소} 건축물 소유자(관리자) 귀하
제목: 「{사업명}」 신청 안내

1. 귀 건축물은 건축물대장 기재 사항을 기준으로 1차 검토한 결과 {판정안내}.
   가. 대지위치: {지번주소}
   나. 도로명주소: {도로명주소}
   다. 사용승인일: {사용승인일} (경과연수 {경과연수})
   라. 주구조 / 주용도: {주구조} / {주용도}
   마. 지상층수 / 연면적: {지상층수} / {연면적}

2. 신청 안내
   가. 접수기간: {접수기간}
   나. 신청방법: {신청방법}
   다. 접수처: {접수처}
   라. 제출서류: {제출서류}
   마. 문의처: {문의처}

3. 본 안내는 지원 대상 선정 통지가 아니며, 최종 지원 여부는 신청 후 현장 확인 및 심사 결과에 따릅니다.
""" + REVIEW_LINE,
    "sms": """[{발신기관}] {지번주소} 건물은 「{사업명}」 {판정안내}. 신청 {접수기간}, 문의 {문의처}
""" + REVIEW_LINE,
}


class TemplateError(ValueError):
    pass


class LetterBlockedError(RuntimeError):
    """안내문을 만들 수 없는 상태(예: 비해당 건물)."""


# ---------------------------------------------------------------- 틀


def make_template(notice: NoticeConditions | None, tone: str) -> str:
    """공고·말투별 틀. 기본 구현은 내장 틀(단계 6에서 LLM 구현으로 교체, 검증 실패 시 내장 틀로 대체)."""
    if tone not in BUILTIN:
        raise TemplateError(f"알 수 없는 말투: {tone}")
    return BUILTIN[tone]


def make_template_llm(notice: NoticeConditions | None, tone: str, provider) -> tuple[str, list[str], bool]:
    """LLM으로 공고·말투별 틀 1개를 만든다. 반환: (틀, 경고, LLM 틀 사용 여부).

    LLM 입력은 공고 조건(접수기간·신청방법·접수처·문의처·제출서류)과 말투 지시뿐이다. 건물 데이터는 넣지 않는다.
    틀 검증을 통과하지 못하거나 호출이 실패하면 내장 틀로 대체하고 경고한다.
    """
    from core.llm import prompts, usage_log
    from core.llm.base import LLMError, Part, doc_hash

    if tone not in BUILTIN:
        raise TemplateError(f"알 수 없는 말투: {tone}")
    fields = notice_values(notice)
    prompt = prompts.template_prompt(tone, fields)
    try:
        text, usage = provider.generate_text(prompts.TEMPLATE_SYSTEM, prompt)
    except LLMError as e:
        return BUILTIN[tone], [f"LLM 틀 생성 실패({e}) → 내장 틀 사용"], False
    if getattr(provider, "name", "") != "mock":
        usage_log.record(usage, "template", doc_hash([Part.of_text(prompt)]))
    text = text.strip().removeprefix("```").removesuffix("```").strip()
    problems = validate_template(text)
    if problems:
        return BUILTIN[tone], ["LLM 틀이 검증을 통과하지 못해 내장 틀을 씁니다: " + "; ".join(problems)], False
    return text, [], getattr(provider, "name", "") != "mock"


def validate_template(text: str) -> list[str]:
    problems = []
    unknown = sorted({p for p in _PLACEHOLDER_RE.findall(text) if p not in ALLOWED})
    if unknown:
        problems.append(f"허용되지 않은 자리표시자: {', '.join('{' + u + '}' for u in unknown)}")
    body = _PLACEHOLDER_RE.sub("", text)
    nums = sorted({m.group(0) for m in _NUMBER_UNIT_RE.finditer(body)})
    if nums:
        problems.append(f"틀 안에 직접 쓴 수치: {', '.join(nums)} (자리표시자를 쓰세요)")
    bad = [w for w in _ASSERTIVE if w in body]
    if bad:
        problems.append(f"확정 표현 금지: {', '.join(bad)}")
    if "{" + STATUS_PLACEHOLDER + "}" not in text:
        problems.append("{판정안내} 자리표시자가 없습니다(1차 후보·확인필요 표현을 코드가 넣습니다)")
    last = [line for line in text.strip().splitlines() if line.strip()][-1:] or [""]
    if "발송 전 담당자 검토" not in last[0]:
        problems.append("마지막 줄에 '발송 전 담당자 검토' 문구가 필요합니다")
    if text.count("{") != text.count("}"):
        problems.append("중괄호 짝이 맞지 않습니다")
    return problems


# ---------------------------------------------------------------- 값 채우기


def _s(v: object) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ""
    return str(v).strip()


def _date(v: object) -> str:
    s = re.sub(r"\D", "", _s(v))
    if len(s) == 8 and s[4:6] != "00" and s[6:] != "00":
        return f"{s[:4]}-{s[4:6]}-{s[6:]}"
    if len(s) >= 4:
        return f"{s[:4]}년" + (f" {int(s[4:6])}월" if len(s) >= 6 and s[4:6] != "00" else "")
    return "(대장 미기재)"


def _num(v: object, unit: str, digits: int = 0) -> str:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return "(대장 미기재)"
    if pd.isna(f):
        return "(대장 미기재)"
    return f"{f:,.{digits}f}{unit}" if digits else f"{int(round(f))}{unit}"


def notice_values(notice: NoticeConditions | None) -> dict[str, str]:
    if notice is None:
        return {k: MISSING for k in NOTICE_PLACEHOLDERS} | {"사업명": "소규모 노후건축물 안전점검 지원", "발신기관": "건축안전센터"}
    period = notice.application_period or (
        f"{notice.apply_start or '?'} ~ {notice.apply_end or '?'}" if (notice.apply_start or notice.apply_end) else ""
    )
    c = notice.contact
    return {
        "접수기간": period or MISSING,
        "신청방법": c.apply_method or MISSING,
        "접수처": c.reception or MISSING,
        "문의처": c.inquiry or MISSING,
        "제출서류": ", ".join(c.documents) or MISSING,
        "사업명": notice.program_name or "소규모 노후건축물 안전점검 지원",
        "발신기관": f"{notice.local_gov} 건축안전센터" if notice.local_gov else "건축안전센터",
    }


def building_values(row: dict) -> dict[str, str]:
    age = row.get("age_years")
    area = row.get("totArea")
    return {
        "지번주소": _s(row.get("platPlc")) or "(대장 미기재)",
        "도로명주소": _s(row.get("newPlatPlc")) or "도로명주소 없음",
        "사용승인일": _date(row.get("useAprDay")),
        "경과연수": f"{int(age)}년" if age is not None and not pd.isna(age) else "확인 필요",
        "주구조": _s(row.get("strctCdNm")) or _s(row.get("etcStrct")) or "(대장 미기재)",
        "주용도": _s(row.get("mainPurpsCdNm")) or _s(row.get("etcPurps")) or "(대장 미기재)",
        "지상층수": _num(row.get("grndFlrCnt"), "층"),
        "연면적": _num(area, "㎡", 2) if area is not None else "(대장 미기재)",
    }


def fill(template: str, row: dict, notice: NoticeConditions | None, today: date | None = None) -> str:
    """today를 주면 접수가 마감된 공고일 때 맨 위에 마감 사실을 적는다(closed_line)."""
    status = row.get("status")
    if status not in STATUS_PHRASE:
        raise LetterBlockedError("안내문은 1차 후보·확인필요 건물만 만듭니다.")
    values = notice_values(notice) | building_values(row) | {STATUS_PLACEHOLDER: STATUS_PHRASE[status]}
    text = _PLACEHOLDER_RE.sub(lambda m: values.get(m.group(1), m.group(0)), template)
    closed = closed_line(notice, today) if today else None
    return f"{closed}\n\n{text}" if closed else text


def recipient(row: dict) -> str:
    return f"{_s(row.get('platPlc')) or '(주소 미기재)'} 건축물 소유자(관리자)"


def sms_bytes(text: str) -> int:
    """문자 길이(바이트). 한글 2바이트(KS X 1001/cp949 기준)."""
    return len(text.encode("cp949", errors="replace"))


def sms_kind(text: str) -> str:
    return "SMS" if sms_bytes(text) <= SMS_LIMIT_BYTES else "LMS"


def closed_line(notice: NoticeConditions | None, today: date) -> str | None:
    """접수가 마감된 공고면 안내문 맨 위에 넣을 문장. 마감 공고로도 안내문은 만들 수 있고, 마감 사실을 다시 적는다."""
    if notice is not None and notice.is_expired(today):
        return f"※ 접수가 마감된 공고(마감 {notice.apply_end})를 기준으로 만든 안내문입니다."
    return None


# ---------------------------------------------------------------- 파일 (메모리에서만)


def letters_docx(rows: pd.DataFrame, template: str, notice: NoticeConditions | None, today: date | None = None) -> bytes:
    """건물별 한 쪽씩(페이지 나눔) 안내문 docx."""
    doc = Document()
    style = doc.styles["Normal"]
    style.font.name = "맑은 고딕"
    style.font.size = Pt(11)
    style.element.rPr.rFonts.set(qn("w:eastAsia"), "맑은 고딕")
    records = rows.to_dict("records")
    for i, row in enumerate(records):
        for line in fill(template, row, notice, today).splitlines():
            doc.add_paragraph(line)
        if i < len(records) - 1:
            doc.add_paragraph().add_run().add_break(WD_BREAK.PAGE)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def targets_csv(rows: pd.DataFrame) -> bytes:
    from core.evaluator import STATUS_LABEL

    out = pd.DataFrame(
        [
            {
                "수신자": recipient(r),
                "지번주소": _s(r.get("platPlc")),
                "도로명주소": _s(r.get("newPlatPlc")),
                "상태": STATUS_LABEL.get(r.get("status"), r.get("status")),
                "사용승인일": _s(r.get("useAprDay")),
                "경과연수": r.get("age_years"),
                "대장PK": _s(r.get("mgmBldrgstPk")),
            }
            for r in rows.to_dict("records")
        ]
    )
    return out.to_csv(index=False).encode("utf-8-sig")
