"""판정 결과 내보내기 (CSV·Excel). 메모리(BytesIO)에서만 만든다. 디스크에 저장하지 않는다."""

from __future__ import annotations

import io
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import date

import pandas as pd

from core.conditions import NoticeConditions
from core.evaluator import REASON_TEXT, STATUS_LABEL
from core.ordinances import SCALE_RULE_LABEL, OrdinanceConditions

# 결과 컬럼(화면·파일 공통). (표시 이름, 만드는 함수)
def _join(v: object, sep: str = "; ") -> str:
    if isinstance(v, (list, tuple)):
        return sep.join(str(x) for x in v if str(x))
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ""
    return str(v)


def _pair(a: object, b: object) -> str:
    a, b = _join(a), _join(b)
    return f"{a} / {b}" if a and b and a != b else (a or b)


def _num(v: object) -> object:
    return None if v is None or (isinstance(v, float) and pd.isna(v)) else v


COLUMNS: list[tuple[str, callable]] = [
    ("지번주소", lambda r: _join(r.get("platPlc"))),
    ("도로명주소", lambda r: _join(r.get("newPlatPlc"))),
    ("건물명", lambda r: _join(r.get("bldNm"))),
    ("동명", lambda r: _join(r.get("dongNm"))),
    ("상태", lambda r: STATUS_LABEL.get(r.get("status"), r.get("status"))),
    ("사유", lambda r: _join(r.get("reason_text"))),
    ("확인필요 사유", lambda r: "; ".join(REASON_TEXT.get(c, c) for c in (r.get("check_reasons") or []))),
    ("현장확인 항목", lambda r: _join(r.get("field_checklist"))),
    ("사용승인일", lambda r: _join(r.get("useAprDay"))),
    ("경과연수", lambda r: _num(r.get("age_years"))),
    ("지상층수", lambda r: _num(r.get("grndFlrCnt"))),
    ("지하층수", lambda r: _num(r.get("ugrndFlrCnt"))),
    ("연면적", lambda r: _num(r.get("totArea"))),
    ("주구조(원문/표준)", lambda r: _pair(r.get("strctCdNm") or r.get("etcStrct"), r.get("structure_std"))),
    ("주용도(원문/기타용도)", lambda r: _pair(r.get("mainPurpsCdNm"), r.get("etcPurps"))),
    ("대장PK", lambda r: _join(r.get("mgmBldrgstPk"))),
]


def result_table(df: pd.DataFrame) -> pd.DataFrame:
    """판정 결과 → 내보내기용 표(한국어 컬럼)."""
    rows = [{name: fn(r) for name, fn in COLUMNS} for r in df.to_dict("records")]
    out = pd.DataFrame(rows, columns=[c for c, _ in COLUMNS])
    if "test_mode" in df.columns and df["test_mode"].any():
        out.insert(0, "시험용", "시험용(다른 지역 공고)")
    return out


def to_csv_bytes(df: pd.DataFrame) -> bytes:
    return result_table(df).to_csv(index=False).encode("utf-8-sig")


@dataclass
class ExportSummary:
    region: str  # 예: 서울특별시 종로구 청운동 외 1개 동
    eval_date: date
    notice: NoticeConditions | None = None
    ordinance: OrdinanceConditions | None = None
    notice_edited: bool = False
    test_mode: bool = False
    unmapped_structures: Counter = field(default_factory=Counter)
    unmapped_uses: Counter = field(default_factory=Counter)
    failed_dongs: dict[str, str] = field(default_factory=dict)


def _bound(v: object, b: str, unit: str) -> str:
    if v is None:
        return ""
    word = {"LE": "이하", "LT": "미만", "GE": "이상", "GT": "초과"}[b]
    return f"{v:g}{unit} {word}" if isinstance(v, float) else f"{v}{unit} {word}"


def _condition_rows(n: NoticeConditions | None, o: OrdinanceConditions | None) -> list[dict]:
    """조건표 시트: 공고·조례를 나란히(병합하지 않음) + 원문 근거."""
    ev = (n.evidence if n else {}) or {}
    rows = []

    def add(name: str, nv: str, ov: str, key: str | None = None) -> None:
        rows.append({"조건": name, "공고 기준": nv, "조례 기준": ov, "공고 원문 근거": ev.get(key or "", "")})

    if n and n.years_basis == "BUILT_BEFORE_YEAR":
        nv_age = f"{n.built_before_year}년 이전" + {True: "(포함)", False: "", None: "(포함 여부 불명)"}[n.built_before_inclusive]
    else:
        nv_age = f"{n.min_years}년 이상" if n and n.min_years else ""
    ov_age = (f"{o.min_years}년 이상" if o.min_years else "매년 정함(법정 30년 이상)") if o else "30년 이상(법정)"
    add("경과연수", nv_age, ov_age, "min_years")
    scale = o.effective_scale() if o else {}
    add(
        "층수",
        " · ".join(x for x in (_bound(n.min_floors, n.min_floors_bound, "층"), _bound(n.max_floors, n.floors_bound, "층")) if x) if n else "",
        " · ".join(x for x in (_bound(scale.get("min_floors"), scale.get("min_floors_bound", "GE"), "층"), _bound(scale.get("max_floors"), scale.get("floors_bound", "LE"), "층")) if x) if o else "",
        "max_floors",
    )
    add(
        "연면적",
        _bound(n.max_area, n.area_bound, "㎡") if n else "",
        _bound(scale.get("max_area"), scale.get("area_bound", "LE"), "㎡") if o else "",
        "max_area",
    )
    add("용도", _join(n.use_filter if n else []), _join(o.use_filter if o else []), "use_filter")
    add("구조", _join(n.structure_filter if n else []), _join(o.structure_filter if o else []), "structure_filter")
    add("제외대상", _join(n.exclusions if n else []), _join(o.exclusions if o else []), "exclusions")
    add("대장 외 조건", _join(n.offmap_conditions if n else []), "위원회 자문·심의" if o and o.committee_required else "", None)
    if o:
        add("조례 규모 기준", "", SCALE_RULE_LABEL.get(o.scale_rule_type, o.scale_rule_type) + (f" ({o.note})" if o.note else ""), None)
        rows.append({"조건": "조례 조문", "공고 기준": "", "조례 기준": o.evidence_definition or "", "공고 원문 근거": ""})
    return rows


def _summary_rows(s: ExportSummary, df: pd.DataFrame) -> list[tuple[str, object]]:
    counts = df["status"].value_counts().to_dict() if "status" in df.columns else {}
    n, o = s.notice, s.ordinance
    rows: list[tuple[str, object]] = [
        ("지역", s.region),
        ("판정 기준일", s.eval_date.isoformat()),
        ("공고", (n.program_name or n.notice_id) if n else "공고 없음 – 조례 기준 판정" if o else "공고·조례 없음 – 법정 기준(30년)만 적용"),
        ("공고 검수 여부", ("검수 완료" if n.reviewed else "미검수") if n else ""),
        ("공고 수정 여부", "담당자가 이 창에서 고친 조건" if s.notice_edited else ""),
        ("접수기간", f"{n.apply_start or '?'} ~ {n.apply_end or '?'}" if n else ""),
        ("시험용 적용", "다른 지역 공고를 시험용으로 적용한 결과" if s.test_mode else ""),
        ("조례", o.ordinance_name if o else "없음"),
        ("조례 시행일", o.effective_date.isoformat() if o and o.effective_date else ""),
        ("조례 규모 기준", SCALE_RULE_LABEL.get(o.scale_rule_type, o.scale_rule_type) if o else ""),
        ("총 건물 수", len(df)),
    ]
    for code, label in STATUS_LABEL.items():
        rows.append((label, int(counts.get(code, 0))))
    if s.failed_dongs:
        rows.append(("조회 실패 동", ", ".join(f"{k}({v})" for k, v in s.failed_dongs.items())))
    rows.append(("안내", "결과는 '자격 후보'이며 최종 선정은 담당자·위원회가 합니다."))
    return [(k, v) for k, v in rows if v != ""]


def to_excel_bytes(df: pd.DataFrame, summary: ExportSummary, include_not_eligible: bool = True) -> bytes:
    table = result_table(df)
    status = df["status"].reset_index(drop=True) if "status" in df.columns else pd.Series(dtype=str)
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        pd.DataFrame(_summary_rows(summary, df), columns=["항목", "값"]).to_excel(xw, sheet_name="요약", index=False)
        pd.DataFrame(_condition_rows(summary.notice, summary.ordinance)).to_excel(xw, sheet_name="조건표", index=False)
        sheets = [("1차후보", "CANDIDATE"), ("확인필요", "NEEDS_CHECK"), ("조례만충족", "ORDINANCE_ONLY")]
        if include_not_eligible:
            sheets.append(("비해당", "NOT_ELIGIBLE"))
        for name, code in sheets:
            table[status == code].to_excel(xw, sheet_name=name, index=False)
        unmapped = [("구조", k, v) for k, v in summary.unmapped_structures.most_common()] + [
            ("용도", k, v) for k, v in summary.unmapped_uses.most_common()
        ]
        pd.DataFrame(unmapped, columns=["구분", "대장 값", "건수"]).to_excel(xw, sheet_name="미매핑값", index=False)
        for ws in xw.book.worksheets:  # 보기 좋게 열 너비만 조정
            for col in ws.columns:
                width = max((len(str(c.value)) if c.value is not None else 0) for c in col[:200])
                ws.column_dimensions[col[0].column_letter].width = min(60, max(8, width * 1.6))
    return buf.getvalue()


def export_filename(sigungu_name: str, dong_names: list[str], on: date, ext: str = "xlsx") -> str:
    dong = dong_names[0] if len(dong_names) == 1 else f"{len(dong_names)}개동"
    safe = lambda s: re.sub(r'[\\/:*?"<>|\s]+', "", s)  # noqa: E731
    return f"{safe(sigungu_name)}_{safe(dong)}_{on.strftime('%Y%m%d')}_판정결과.{ext}"
