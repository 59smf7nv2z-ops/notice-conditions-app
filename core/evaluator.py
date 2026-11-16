"""판정 엔진 v2.

공고 조건표와 조례 조건표를 병합하지 않고 각각 평가한 뒤 4상태를 정한다(.cursor/rules/project.mdc).

- 주 조건표: 공고(APPLY_INSPECTION) → 없으면 조례 → 둘 다 없으면 법정 30년
- 주 조건표 전부 PASS → CANDIDATE
- FAIL 없음 + UNKNOWN 있음 → NEEDS_CHECK
- FAIL 있음 → 공고가 주 조건표이고 조례에 규모 수치가 있으며 조례 평가가 전부 PASS면 ORDINANCE_ONLY, 아니면 NOT_ELIGIBLE
- 대장 외 조건(위원회 심사, 민간건축물 여부 등)은 상태를 바꾸지 않고 field_checklist로 붙인다.

경과연수는 사용승인일 → 기준일까지 만 나이식으로 센다.
(legacy 판정 코드를 받지 못해 legacy 방식과의 비교는 아직 못 했다. scripts/legacy/README.md)
"""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass, field
from datetime import date

import pandas as pd

from core import normalize
from core.conditions import NoticeConditions
from core.ordinances import LEGAL_MIN_YEARS, OrdinanceConditions

PASS, FAIL, UNKNOWN = "PASS", "FAIL", "UNKNOWN"
CANDIDATE, NEEDS_CHECK, ORDINANCE_ONLY, NOT_ELIGIBLE = "CANDIDATE", "NEEDS_CHECK", "ORDINANCE_ONLY", "NOT_ELIGIBLE"

STATUS_LABEL = {
    CANDIDATE: "1차 후보",
    NEEDS_CHECK: "확인필요",
    ORDINANCE_ONLY: "조례만 충족",
    NOT_ELIGIBLE: "비해당",
}

REASON_TEXT = {
    # 확인필요(UNKNOWN)
    "APPROVAL_DATE_MISSING": "사용승인일이 대장에 없음",
    "APPROVAL_DATE_INVALID": "사용승인일 형식을 해석할 수 없음",
    "APPROVAL_YEAR_ONLY_BOUNDARY": "사용승인일이 연(월)만 있어 경계 연도에서 경과연수를 확정할 수 없음",
    "BUILT_YEAR_BOUNDARY_UNCLEAR": "공고의 '○○년 이전'이 해당 연도를 포함하는지 불명",
    "ORD_YEARS_YEARLY": "조례가 점검 대상 경과연수를 매년 따로 정함",
    "FLOORS_MISSING": "층수가 대장에 없음",
    "AREA_MISSING": "연면적이 대장에 없음",
    "ORD_SCALE_EXTERNAL_REF": "조례가 외부 기준(구조기준규칙·건설산업기본법)을 참조해 대장 수치로 확정할 수 없음",
    "STRUCTURE_UNMAPPED": "대장 구조명을 표준 구조로 정규화하지 못함",
    "STRUCTURE_CONDITION_UNPARSED": "구조 조건 문구를 해석하지 못함",
    "USE_UNMAPPED": "대장 용도를 표준 용도로 정규화하지 못함",
    "USE_MIXED": "복합·기타용도라 용도 조건 해석이 필요함",
    "HOUSING_SCOPE_UNCLEAR": "공고가 '주택'이라고만 해 공동주택 포함 여부가 불명",
    "USE_CONDITION_UNPARSED": "용도 조건 문구를 해석하지 못함",
    "REGISTER_TYPE_MISSING": "일반/집합 구분이 대장에 없음",
    # 불충족(FAIL)
    "FAIL_AGE": "경과연수 미달",
    "FAIL_FLOORS": "층수 조건 불충족",
    "FAIL_AREA": "연면적 조건 불충족",
    "FAIL_USE": "용도 조건 불충족",
    "FAIL_STRUCTURE": "구조 조건 불충족",
    "FAIL_COLLECTIVE": "집합건물 제외 대상",
    "FAIL_MULTI_HOUSING": "공동주택 제외 대상",
    "ANNEX_BUILDING": "부속건축물(기본 제외)",
    # 상태 설명
    "ALL_PASS": "주 조건표의 모든 조건을 대장 값으로 충족",
    "NOTICE_FAIL_ORDINANCE_PASS": "공고 조건은 불충족, 조례 조건은 충족(잠재 대상)",
}

FAIL_CODE = {
    "경과연수": "FAIL_AGE",
    "층수": "FAIL_FLOORS",
    "연면적": "FAIL_AREA",
    "용도": "FAIL_USE",
    "구조": "FAIL_STRUCTURE",
    "집합건물 제외": "FAIL_COLLECTIVE",
    "공동주택 제외": "FAIL_MULTI_HOUSING",
}

BOUND_WORD = {"LE": "이하", "LT": "미만", "GE": "이상", "GT": "초과"}


@dataclass
class EvalOptions:
    include_annex: bool = False  # 부속건축물도 판정
    exclude_collective: bool | None = None  # True면 공고·조례 모두 집합건물 제외(legacy '집합건물 제외' 설정)


@dataclass
class Check:
    name: str
    result: str
    criterion: str
    value: str
    reason: str | None = None

    def as_dict(self) -> dict:
        return {"조건": self.name, "기준": self.criterion, "대장값": self.value, "결과": self.result, "사유": self.reason}


@dataclass
class Table:
    """공고·조례·법정 기준을 같은 모양으로 평가하기 위한 내부 표현."""

    label: str  # 공고 | 조례 | 법정
    age_ref: date
    years_basis: str = "ELAPSED_YEARS"
    min_years: int | None = LEGAL_MIN_YEARS
    years_yearly: bool = False
    built_before_year: int | None = None
    built_before_inclusive: bool | None = None
    max_floors: int | None = None
    floors_bound: str = "LE"
    min_floors: int | None = None
    min_floors_bound: str = "GE"
    floors_basis: str = "GROUND_ONLY"
    max_area: float | None = None
    area_bound: str = "LE"
    scale_external: str | None = None
    use_tokens: list[str] = field(default_factory=list)
    use_unparsed: list[str] = field(default_factory=list)
    structure_tokens: list[str] = field(default_factory=list)
    structure_unparsed: list[str] = field(default_factory=list)
    collective_excluded: bool = False
    multi_housing_excluded: bool = False
    checklist: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


# ---------------------------------------------------------------- 조건표 만들기


def _use_tokens(values: list[str]) -> tuple[list[str], list[str]]:
    known = normalize.standard_uses() | set(normalize.USE_SUBTYPES) | {normalize.HOUSING_BROAD}
    tokens: list[str] = []
    unparsed: list[str] = []
    for v in values:
        if v.startswith("!") or v in known:
            tokens.append(v)
            continue
        t, u = normalize.use_tokens(v)
        tokens += t
        unparsed += u
    return list(dict.fromkeys(tokens)), unparsed


def _structure_tokens(values: list[str]) -> tuple[list[str], list[str]]:
    tokens: list[str] = []
    unparsed: list[str] = []
    for v in values:
        if v in normalize.STRUCTURE_STD:
            tokens.append(v)
            continue
        t, u = normalize.structure_tokens(v)
        tokens += t
        unparsed += u
    return list(dict.fromkeys(tokens)), unparsed


def table_from_notice(n: NoticeConditions, eval_date: date, options: EvalOptions) -> tuple[Table, list[str]]:
    ref, warn = n.age_reference_date(eval_date)
    ut, uu = _use_tokens(n.use_filter)
    st, su = _structure_tokens(n.structure_filter)
    covered = ("집합건", "공동주택")
    checklist = list(n.offmap_conditions) + [
        f"공고 제외대상 해당 여부: {e}" for e in n.exclusions if not any(w in e for w in covered)
    ]
    t = Table(
        label="공고",
        age_ref=ref,
        years_basis=n.years_basis,
        min_years=n.min_years,
        built_before_year=n.built_before_year,
        built_before_inclusive=n.built_before_inclusive,
        max_floors=n.max_floors,
        floors_bound=n.floors_bound,
        min_floors=n.min_floors,
        min_floors_bound=n.min_floors_bound,
        floors_basis=n.floors_basis,
        max_area=n.max_area,
        area_bound=n.area_bound,
        use_tokens=ut,
        use_unparsed=uu,
        structure_tokens=st,
        structure_unparsed=su,
        collective_excluded=bool(n.collective_excluded) or bool(options.exclude_collective),
        multi_housing_excluded=bool(n.multi_housing_excluded),
        checklist=checklist,
    )
    if n.years_basis == "ELAPSED_YEARS" and n.min_years is None:
        t.min_years = LEGAL_MIN_YEARS
        t.notes.append("공고에 경과연수 조건이 없어 법정 기준(30년)을 적용")
    return t, [warn] if warn else []


def table_from_ordinance(o: OrdinanceConditions, eval_date: date, options: EvalOptions) -> Table:
    s = o.effective_scale()
    ut, uu = _use_tokens(o.use_filter)
    st, su = _structure_tokens(o.structure_filter)
    checklist = []
    if o.committee_required:
        checklist.append("조례: 위원회 자문·심의 결과 점검 필요 인정 여부")
    if o.approver:
        checklist.append(f"조례: {o.approver}의 점검 필요 인정 여부")
    if o.private_only:
        checklist.append("조례: 민간건축물 여부(공공건축물 제외)")
    if o.multi_housing_excluded == "MANDATORY_MGMT":
        checklist.append("조례: 공동주택관리법상 의무관리대상 공동주택 여부")
    covered = ("집합건",) + (("공동주택",) if o.multi_housing_excluded == "ALL" else ())
    checklist += [f"조례 제외대상 해당 여부: {e}" for e in o.exclusions if not any(w in e for w in covered)]
    t = Table(
        label="조례",
        age_ref=eval_date,
        min_years=o.min_years if o.min_years is not None else LEGAL_MIN_YEARS,
        years_yearly=o.min_years is None,
        max_floors=s["max_floors"],
        floors_bound=s["floors_bound"],
        min_floors=s["min_floors"],
        min_floors_bound=s["min_floors_bound"],
        max_area=s["max_area"],
        area_bound=s["area_bound"],
        use_tokens=ut,
        use_unparsed=uu,
        structure_tokens=st,
        structure_unparsed=su,
        collective_excluded=o.collective_excluded or bool(options.exclude_collective),
        multi_housing_excluded=o.multi_housing_excluded == "ALL",
        checklist=checklist,
    )
    if o.scale_rule_type in ("STRUCTURE_RULE_REF", "CONSTRUCTION_ACT_REF") and not o.manual_override:
        if o.scale_rule_type == "STRUCTURE_RULE_REF":
            t.scale_external = "「건축물의 구조기준 등에 관한 규칙」 제3조제2항의 소규모건축물"
            t.checklist.insert(0, "조례: 구조기준규칙상 소규모건축물 해당 여부")
        else:
            t.scale_external = "「건설산업기본법」 제41조에 따른 건설사업자 시공 건축물 이외"
            t.checklist.insert(0, "조례: 건설산업기본법 제41조에 따른 건설사업자 시공 여부")
    if o.scale_rule_type in ("DISCRETION", "NONE"):
        t.notes.append("조례에 규모 수치 없음")
    if o.manual_override:
        t.notes.append("조례 규모 수치: 담당자 입력값 사용")
    return t


def legal_table(eval_date: date, options: EvalOptions) -> Table:
    t = Table(label="법정", age_ref=eval_date, collective_excluded=bool(options.exclude_collective))
    t.notes.append("공고·조례 없음: 법정 기준(사용승인 후 30년)만 적용")
    return t


# ---------------------------------------------------------------- 값 해석


def _num(v: object) -> float | None:
    if v is None:
        return None
    try:
        f = float(str(v).replace(",", "").strip())
    except ValueError:
        return None
    return None if pd.isna(f) else f


def _str(v: object) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ""
    return str(v).strip()


@dataclass(frozen=True)
class Approval:
    """사용승인일. 연·월만 있으면 가능한 날짜 범위로 둔다."""

    earliest: date | None
    latest: date | None
    raw: str
    problem: str | None = None  # APPROVAL_DATE_MISSING | APPROVAL_DATE_INVALID

    @property
    def exact(self) -> bool:
        return self.earliest is not None and self.earliest == self.latest


def parse_approval(value: object) -> Approval:
    raw = _str(value)
    digits = re.sub(r"\D", "", raw)
    if not digits:
        return Approval(None, None, raw, "APPROVAL_DATE_MISSING")
    try:
        if len(digits) == 8:
            y, m, d = int(digits[:4]), int(digits[4:6]), int(digits[6:])
            if m == 0:
                return Approval(date(y, 1, 1), date(y, 12, 31), raw)
            if d == 0:
                return Approval(date(y, m, 1), date(y, m, calendar.monthrange(y, m)[1]), raw)
            try:
                return Approval(date(y, m, d), date(y, m, d), raw)
            except ValueError:  # 예: 2월 30일 → 월까지만 믿는다
                return Approval(date(y, m, 1), date(y, m, calendar.monthrange(y, m)[1]), raw)
        if len(digits) == 6:
            y, m = int(digits[:4]), int(digits[4:])
            if m == 0:
                return Approval(date(y, 1, 1), date(y, 12, 31), raw)
            return Approval(date(y, m, 1), date(y, m, calendar.monthrange(y, m)[1]), raw)
        if len(digits) == 4:
            y = int(digits)
            return Approval(date(y, 1, 1), date(y, 12, 31), raw)
    except ValueError:
        pass
    return Approval(None, None, raw, "APPROVAL_DATE_INVALID")


def full_years(since: date, ref: date) -> int:
    """만 나이식 경과연수."""
    return ref.year - since.year - ((ref.month, ref.day) < (since.month, since.day))


def age_years(value: object, ref: date) -> int | None:
    a = parse_approval(value)
    return full_years(a.earliest, ref) if a.exact else None


# ---------------------------------------------------------------- 조건 단위 평가


def _bound_ok(v: float, limit: float, bound: str) -> bool:
    return {"LE": v <= limit, "LT": v < limit, "GE": v >= limit, "GT": v > limit}[bound]


def _fmt(n: float) -> str:
    return f"{n:g}"


def _check_age(row: dict, t: Table) -> Check:
    a = parse_approval(row.get("useAprDay"))
    shown = a.raw or "(없음)"
    if t.years_basis == "BUILT_BEFORE_YEAR":
        y = t.built_before_year
        crit = f"{y}년 {'이전(포함)' if t.built_before_inclusive else '이전' if t.built_before_inclusive is False else '이전(포함 여부 불명)'}"
        if a.problem:
            return Check("경과연수", UNKNOWN, crit, shown, a.problem)
        first, last = a.earliest.year, a.latest.year
        def ok(year: int) -> bool | None:
            if year < y:
                return True
            if year > y:
                return False
            return t.built_before_inclusive
        lo, hi = ok(first), ok(last)
        if lo is True and hi is True:
            return Check("경과연수", PASS, crit, shown)
        if lo is False and hi is False:
            return Check("경과연수", FAIL, crit, shown)
        reason = "BUILT_YEAR_BOUNDARY_UNCLEAR" if t.built_before_inclusive is None else "APPROVAL_YEAR_ONLY_BOUNDARY"
        return Check("경과연수", UNKNOWN, crit, shown, reason)

    need = t.min_years if t.min_years is not None else LEGAL_MIN_YEARS
    crit = f"사용승인 후 {need}년 이상 (기준일 {t.age_ref.isoformat()})"
    if t.years_yearly:
        crit += " · 조례가 연수를 매년 정함"
    if a.problem:
        return Check("경과연수", UNKNOWN, crit, shown, a.problem)
    old, young = full_years(a.earliest, t.age_ref), full_years(a.latest, t.age_ref)
    value = f"{young}년 ({shown})" if a.exact else f"{young}~{old}년 ({shown})"
    if young >= need:
        if t.years_yearly:
            return Check("경과연수", UNKNOWN, crit, value, "ORD_YEARS_YEARLY")
        return Check("경과연수", PASS, crit, value)
    if old < need:
        return Check("경과연수", FAIL, crit, value)
    return Check("경과연수", UNKNOWN, crit, value, "APPROVAL_YEAR_ONLY_BOUNDARY")


def _check_floors(row: dict, t: Table) -> Check | None:
    if t.max_floors is None and t.min_floors is None:
        return None
    parts = []
    if t.min_floors is not None:
        parts.append(f"{t.min_floors}층 {BOUND_WORD[t.min_floors_bound]}")
    if t.max_floors is not None:
        parts.append(f"{t.max_floors}층 {BOUND_WORD[t.floors_bound]}")
    basis = "지상+지하" if t.floors_basis == "GROUND_AND_UNDERGROUND" else "지상"
    crit = f"{basis} " + " · ".join(parts)
    g = _num(row.get("grndFlrCnt"))
    u = _num(row.get("ugrndFlrCnt")) or 0.0
    if g is None or g <= 0:
        return Check("층수", UNKNOWN, crit, "(없음)", "FLOORS_MISSING")
    v = g + u if t.floors_basis == "GROUND_AND_UNDERGROUND" else g
    shown = f"{_fmt(v)}층" + (f" (지상 {_fmt(g)}, 지하 {_fmt(u)})" if t.floors_basis == "GROUND_AND_UNDERGROUND" else "")
    ok = True
    if t.max_floors is not None:
        ok &= _bound_ok(v, t.max_floors, t.floors_bound)
    if t.min_floors is not None:
        ok &= _bound_ok(v, t.min_floors, t.min_floors_bound)
    return Check("층수", PASS if ok else FAIL, crit, shown)


def _check_area(row: dict, t: Table) -> Check | None:
    if t.max_area is None:
        return None
    crit = f"연면적 {_fmt(t.max_area)}㎡ {BOUND_WORD[t.area_bound]}"
    v = _num(row.get("totArea"))
    if v is None or v <= 0:
        return Check("연면적", UNKNOWN, crit, "(없음)", "AREA_MISSING")
    return Check("연면적", PASS if _bound_ok(v, t.max_area, t.area_bound) else FAIL, crit, f"{_fmt(v)}㎡")


def _check_use(row: dict, t: Table, info: normalize.UseInfo) -> Check | None:
    if not t.use_tokens and not t.use_unparsed:
        return None
    crit = " / ".join([x.replace("!", "제외: ") for x in t.use_tokens] + t.use_unparsed)
    shown = " / ".join(x for x in (_str(row.get("mainPurpsCdNm")), _str(row.get("etcPurps"))) if x) or "(없음)"
    if t.use_tokens:
        result, reason = normalize.match_use(t.use_tokens, info)
        if result == PASS or not t.use_unparsed:
            return Check("용도", result, crit, shown, reason)
    return Check("용도", UNKNOWN, crit, shown, "USE_CONDITION_UNPARSED")


def _check_structure(row: dict, t: Table, std: str | None) -> Check | None:
    if not t.structure_tokens and not t.structure_unparsed:
        return None
    crit = " / ".join(t.structure_tokens + t.structure_unparsed)
    shown = " / ".join(x for x in (_str(row.get("strctCdNm")), _str(row.get("etcStrct"))) if x) or "(없음)"
    if std is None:
        return Check("구조", UNKNOWN, crit, shown, "STRUCTURE_UNMAPPED")
    if std in t.structure_tokens:
        return Check("구조", PASS, crit, f"{shown} → {std}")
    if t.structure_unparsed:
        return Check("구조", UNKNOWN, crit, f"{shown} → {std}", "STRUCTURE_CONDITION_UNPARSED")
    return Check("구조", FAIL, crit, f"{shown} → {std}")


def _check_collective(row: dict, t: Table) -> Check | None:
    if not t.collective_excluded:
        return None
    v = _str(row.get("regstrGbCdNm"))
    if not v:
        return Check("집합건물 제외", UNKNOWN, "집합건물 제외", "(없음)", "REGISTER_TYPE_MISSING")
    return Check("집합건물 제외", FAIL if "집합" in v else PASS, "집합건물 제외", v)


def _check_multi_housing(row: dict, t: Table, info: normalize.UseInfo) -> Check | None:
    if not t.multi_housing_excluded:
        return None
    shown = info.std or "(미정규화)"
    if info.std is None and not info.subtypes:
        return Check("공동주택 제외", UNKNOWN, "공동주택 제외", shown, "USE_UNMAPPED")
    is_multi = info.std == "공동주택" or any(normalize.USE_SUBTYPES.get(s) == "공동주택" for s in info.subtypes)
    return Check("공동주택 제외", FAIL if is_multi else PASS, "공동주택 제외", shown)


def evaluate_table(row: dict, table: Table) -> list[Check]:
    """조건 단위 평가 → [Check(조건명, PASS|FAIL|UNKNOWN, 기준, 대장값, 사유)]."""
    info = normalize.use_info(row.get("mainPurpsCdNm"), row.get("etcPurps"))
    std = row.get("structure_std") if "structure_std" in row else normalize.structure_std(row.get("strctCdNm"), row.get("etcStrct"))
    std = _str(std) or None  # NaN·빈 값 → None
    checks = [_check_age(row, table)]
    for c in (
        _check_floors(row, table),
        _check_area(row, table),
        _check_use(row, table, info),
        _check_structure(row, table, std),
        _check_collective(row, table),
        _check_multi_housing(row, table, info),
    ):
        if c is not None:
            checks.append(c)
    if table.scale_external:
        checks.append(Check("규모(외부 기준)", UNKNOWN, table.scale_external, "대장으로 확인 불가", "ORD_SCALE_EXTERNAL_REF"))
    return checks


# ---------------------------------------------------------------- 상태 결정


def _status(primary: list[Check], secondary: list[Check] | None, notice_primary: bool, ord_has_numbers: bool) -> tuple[str, list[str]]:
    fails = [c for c in primary if c.result == FAIL]
    unknowns = [c for c in primary if c.result == UNKNOWN]
    if not fails and not unknowns:
        return CANDIDATE, ["ALL_PASS"]
    if not fails:
        return NEEDS_CHECK, list(dict.fromkeys(c.reason for c in unknowns if c.reason))
    fail_codes = list(dict.fromkeys(FAIL_CODE.get(c.name, "FAIL_" + c.name) for c in fails))
    if notice_primary and ord_has_numbers and secondary and all(c.result == PASS for c in secondary):
        return ORDINANCE_ONLY, ["NOTICE_FAIL_ORDINANCE_PASS"] + fail_codes
    return NOT_ELIGIBLE, fail_codes


def _reason_text(codes: list[str], label: str) -> str:
    texts = [REASON_TEXT.get(c, c) for c in codes]
    if codes == ["ALL_PASS"]:
        texts = [f"{label} 조건을 모두 충족(대장 기준)"]
    return "; ".join(texts)


def evaluate(
    df: pd.DataFrame,
    notice: NoticeConditions | None,
    ordinance: OrdinanceConditions | None,
    eval_date: date,
    options: EvalOptions | None = None,
) -> pd.DataFrame:
    """대장 표제부 DataFrame → 판정 결과 DataFrame(입력 컬럼 + 판정 컬럼).

    notice가 신청형 안전점검(APPLY_INSPECTION)이 아니면 NotJudgeableNoticeError.
    """
    options = options or EvalOptions()
    warnings: list[str] = []
    if notice is not None:
        notice.require_judgeable()
        primary_table, w = table_from_notice(notice, eval_date, options)
        warnings += w
        secondary_table = table_from_ordinance(ordinance, eval_date, options) if ordinance else legal_table(eval_date, options)
    elif ordinance is not None:
        primary_table, secondary_table = table_from_ordinance(ordinance, eval_date, options), None
    else:
        primary_table, secondary_table = legal_table(eval_date, options), None
    notice_primary = notice is not None
    ord_numbers = bool(ordinance and ordinance.has_scale_numbers())

    if "structure_std" not in df.columns or "use_std" not in df.columns:
        df = normalize.normalize_df(df).df

    out_cols: dict[str, list] = {
        k: []
        for k in (
            "status",
            "status_label",
            "reasons",
            "reason_text",
            "check_reasons",
            "field_checklist",
            "notice_detail",
            "ordinance_detail",
            "age_years",
            "primary_table",
            "notes",
        )
    }
    for row in df.to_dict("records"):
        age = age_years(row.get("useAprDay"), primary_table.age_ref)
        if not options.include_annex and "부속" in _str(row.get("mainAtchGbCdNm")):
            status, codes = NOT_ELIGIBLE, ["ANNEX_BUILDING"]
            p_checks: list[Check] = []
            s_checks: list[Check] | None = None
        else:
            p_checks = evaluate_table(row, primary_table)
            s_checks = evaluate_table(row, secondary_table) if secondary_table else None
            status, codes = _status(p_checks, s_checks, notice_primary, ord_numbers)
        notice_checks = p_checks if notice_primary else None
        ord_checks = s_checks if notice_primary else p_checks
        out_cols["status"].append(status)
        out_cols["status_label"].append(STATUS_LABEL[status])
        out_cols["reasons"].append(codes)
        out_cols["reason_text"].append(_reason_text(codes, primary_table.label))
        out_cols["check_reasons"].append(codes if status == NEEDS_CHECK else [])
        out_cols["field_checklist"].append(list(primary_table.checklist) if status in (CANDIDATE, NEEDS_CHECK) else [])
        out_cols["notice_detail"].append([c.as_dict() for c in notice_checks] if notice_checks else [])
        out_cols["ordinance_detail"].append([c.as_dict() for c in ord_checks] if ord_checks else [])
        out_cols["age_years"].append(age)
        out_cols["primary_table"].append(primary_table.label)
        out_cols["notes"].append(primary_table.notes + (secondary_table.notes if secondary_table else []) + warnings)
    result = df.copy()
    for k, v in out_cols.items():
        result[k] = pd.Series(v, index=result.index, dtype="Int64" if k == "age_years" else "object")
    return result


def status_counts(result: pd.DataFrame) -> dict[str, int]:
    counts = result["status"].value_counts().to_dict()
    return {s: int(counts.get(s, 0)) for s in (CANDIDATE, NEEDS_CHECK, ORDINANCE_ONLY, NOT_ELIGIBLE)}
