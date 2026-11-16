"""분류·추출: 공고 파일 조각 → 사업유형 / NoticeConditions.

- classify: 사업유형 + 근거. APPLY_INSPECTION이 아니면 추출하지 않는다.
- extract: ExtractOut(LLM) → NoticeConditions(코드 변환). 층수·연면적의 이하/미만, 날짜, 용도·구조 표준화는 코드가 한다.
- 결과는 reviewed=False. 사람이 검수 후 저장한다.
- 사용량은 data/logs/llm_usage.csv에 토큰·문서 해시만 남긴다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from core import normalize, regions
from core.conditions import (
    BusinessType,
    Contact,
    NoticeConditions,
    parse_area_text,
    parse_floor_text,
)
from core.llm import prompts, usage_log
from core.llm.base import LLMProvider, Part, Usage, doc_hash
from core.llm.schemas import ClassifyOut, ExtractOut

SELECTION_METHODS = {"심사", "선착순", "예산소진", "직권", "기타"}


@dataclass
class ClassifyResult:
    business_type: BusinessType
    evidence: str | None
    reason: str
    has_repair_section: bool
    usage: Usage

    @property
    def is_apply_inspection(self) -> bool:
        return self.business_type == BusinessType.APPLY_INSPECTION


@dataclass
class ExtractResult:
    notice: NoticeConditions
    issues: list[str] = field(default_factory=list)  # 사람이 확인할 변환 문제
    usage: Usage | None = None
    raw: ExtractOut | None = None


def classify(parts: list[Part], provider: LLMProvider, log: bool = True) -> ClassifyResult:
    out, usage = provider.generate_json(prompts.CLASSIFY_SYSTEM, parts, ClassifyOut)
    if log and provider.name != "mock":
        usage_log.record(usage, "classify", doc_hash(parts))
    return ClassifyResult(BusinessType(out.business_type), out.evidence, out.reason, out.has_repair_section, usage)


def _date(v: str | None, label: str, issues: list[str]) -> date | None:
    if not v:
        return None
    m = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", v.strip())
    if not m:
        issues.append(f"{label} '{v}'를 날짜로 읽지 못해 비웠습니다")
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        issues.append(f"{label} '{v}'는 없는 날짜라 비웠습니다")
        return None


def _slug(text: str) -> str:
    return re.sub(r"[^\w가-힣-]+", "_", text).strip("_")[:60] or "notice"


def to_notice(out: ExtractOut, notice_id: str | None = None, business_type: BusinessType = BusinessType.APPLY_INSPECTION) -> ExtractResult:
    """LLM 출력 → NoticeConditions. 해석 못 한 값은 비우고 issues에 남긴다(추측하지 않는다)."""
    issues: list[str] = []
    ev: dict[str, str] = {}

    def keep(name: str, f) -> None:
        if getattr(f, "evidence", None):
            ev[name] = f.evidence

    # 지역 → 시군구코드: 정확히 일치할 때만
    codes: list[str] = []
    gov = out.local_gov.value
    if gov:
        p = gov.split(maxsplit=1)
        m = regions.match_sigungu(p[0], p[1] if len(p) > 1 else "")
        codes = m["codes"]
        if not codes:
            issues.append(f"지자체 '{gov}'를 시군구코드로 찾지 못했습니다({m['kind']}). 직접 고르세요")
    keep("local_gov", out.local_gov)

    fl = parse_floor_text(out.floors_text.value) if out.floors_text.value else None
    if out.floors_text.value and not fl:
        issues.append(f"층수 '{out.floors_text.value}'에서 이하/미만을 읽지 못했습니다")
    keep("max_floors", out.floors_text)
    ar = parse_area_text(out.area_text.value) if out.area_text.value else None
    if out.area_text.value and not ar:
        issues.append(f"연면적 '{out.area_text.value}'에서 ㎡ 수치와 이하/미만을 읽지 못했습니다")
    keep("max_area", out.area_text)

    uses: list[str] = []
    for u in out.use_conditions.value:
        t, bad = normalize.use_tokens(u)
        uses += t
        issues += [f"용도 '{b}'를 표준 용도로 바꾸지 못했습니다" for b in bad]
    keep("use_filter", out.use_conditions)
    structs: list[str] = []
    for s in out.structure_conditions.value:
        t, bad = normalize.structure_tokens(s)
        structs += t
        issues += [f"구조 '{b}'를 표준 구조로 바꾸지 못했습니다" for b in bad]
    keep("structure_filter", out.structure_conditions)

    sel = out.selection_method.value
    if sel and sel not in SELECTION_METHODS:
        issues.append(f"선정방식 '{sel}'은 정해진 분류가 아니라 '기타'로 둡니다")
        sel = "기타"

    years_basis = "ELAPSED_YEARS"
    if out.built_before_year.value and not out.min_years.value:
        years_basis = "BUILT_BEFORE_YEAR"
    if out.built_before_year.value and out.min_years.value:
        issues.append("경과연수와 'OO년 이전' 기준이 둘 다 있어 경과연수 기준을 씁니다. 원문을 확인하세요")

    start = _date(out.apply_start.value, "접수 시작일", issues)
    end = _date(out.apply_end.value, "접수 종료일", issues)
    if start and end and start > end:
        issues.append("접수 시작일이 종료일보다 늦어 날짜를 비웠습니다")
        start = end = None

    for name, f in (
        ("min_years", out.min_years), ("built_before_year", out.built_before_year), ("application_period", out.application_period),
        ("exclusions", out.exclusions), ("selection_method", out.selection_method), ("priority_rules", out.priority_criteria),
        ("offmap_conditions", out.offmap_conditions), ("support_content", out.support_content), ("program_name", out.program_name),
        ("contact.reception", out.reception), ("contact.inquiry", out.inquiry), ("contact.apply_method", out.apply_method),
        ("contact.documents", out.documents), ("collective_excluded", out.collective_excluded),
        ("multi_housing_excluded", out.multi_housing_excluded), ("notice_date", out.notice_date),
    ):
        keep(name, f)

    nid = notice_id or _slug(f"{gov or '지역미상'}_{out.year.value or ''}_{out.program_name.value or '공고'}")
    notice = NoticeConditions(
        notice_id=nid,
        local_gov=gov,
        program_name=out.program_name.value,
        year=out.year.value,
        season=out.season.value,
        business_type=business_type,
        sigungu_codes=codes,
        notice_date=_date(out.notice_date.value, "공고일", issues),
        apply_start=start,
        apply_end=end,
        application_period=out.application_period.value,
        years_basis=years_basis,
        min_years=out.min_years.value,
        built_before_year=out.built_before_year.value if years_basis == "BUILT_BEFORE_YEAR" else None,
        built_before_inclusive=out.built_before_inclusive.value if years_basis == "BUILT_BEFORE_YEAR" else None,
        max_floors=fl[0] if fl else None,
        floors_bound=fl[1] if fl else "LE",
        floors_basis="GROUND_AND_UNDERGROUND" if out.floors_include_underground.value else "GROUND_ONLY",
        max_area=ar[0] if ar else None,
        area_bound=ar[1] if ar else "LE",
        use_filter=list(dict.fromkeys(uses)),
        structure_filter=list(dict.fromkeys(structs)),
        collective_excluded=out.collective_excluded.value,
        multi_housing_excluded=out.multi_housing_excluded.value,
        exclusions=out.exclusions.value,
        selection_method=sel,
        priority_rules=out.priority_criteria.value,
        offmap_conditions=out.offmap_conditions.value,
        support_content=out.support_content.value,
        scale=out.scale.value,
        contact=Contact(
            reception=out.reception.value, inquiry=out.inquiry.value,
            apply_method=out.apply_method.value, documents=out.documents.value,
        ),
        source_type=out.source_type,
        reviewed=False,
        evidence=ev,
    )
    if out.source_type in ("NEWS", "PRESS_RELEASE"):
        issues.append("뉴스·보도자료 출처입니다. 원문 공고를 확인하세요")
    if notice.min_years is None and notice.years_basis == "ELAPSED_YEARS":
        issues.append("경과연수 조건을 찾지 못했습니다(판정 때 법정 30년 적용)")
    return ExtractResult(notice, issues, raw=out)


def extract(parts: list[Part], provider: LLMProvider, notice_id: str | None = None, log: bool = True) -> ExtractResult:
    with_hint = parts + [Part.of_text(prompts.EXTRACT_HINT)]
    out, usage = provider.generate_json(prompts.EXTRACT_SYSTEM, with_hint, ExtractOut)
    if log and provider.name != "mock":
        usage_log.record(usage, "extract", doc_hash(parts))
    res = to_notice(out, notice_id)
    res.usage = usage
    return res
