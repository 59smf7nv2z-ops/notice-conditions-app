"""여러 글(구청 공고·보도자료·뉴스)에서 뽑은 조건을 한 공고 조건으로 합친다.

규칙(추측하지 않는다)
- 회차: 연도가 가장 최근인 글들만 합친다. 그보다 오래된 해의 글은 빼고 issues에 남긴다(조건이 해마다 바뀔 수 있음).
- 우선순위: 정식 공고 → 보도자료 → 뉴스, 같으면 들어온 순서(검색 관련도순).
- 값 하나짜리(경과연수, 층수·연면적과 그 이하/미만, 접수기간 등)는 우선순위가 가장 높은 글에서 가져온다.
  묶인 값(층수+경계, 접수 시작+종료+원문 기간)은 같은 글에서 함께 가져온다.
  다른 글의 값이 다르면 '출처마다 다름'으로 issues에 남긴다(담당자가 원문 확인).
- 용도·구조 제한은 합치지 않고(합집합은 대상을 넓힌다) 첫 글의 것을 쓴다. 다르면 issues.
- 목록(제외대상, 우선순위, 대장 외 조건, 지원내용, 제출서류)은 중복 없이 모두 모은다.
- 원문 근거에는 [출처 n]을 붙인다. n은 sources 순서(1부터).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from core.conditions import Contact, NoticeConditions

SOURCE_RANK = {"OFFICIAL_NOTICE": 0, "PRESS_RELEASE": 1, "LEAFLET": 1, "NEWS": 2}
SOURCE_LABEL = {"OFFICIAL_NOTICE": "공고", "PRESS_RELEASE": "보도자료", "LEAFLET": "리플릿", "NEWS": "뉴스"}

# 함께 가져오는 값 묶음: (이름, 판단 기준 필드, 묶음 필드)
GROUPS: list[tuple[str, str, tuple[str, ...]]] = [
    ("경과연수", "min_years", ("min_years",)),
    ("기준 연도", "built_before_year", ("built_before_year", "built_before_inclusive", "years_basis")),
    ("층수", "max_floors", ("max_floors", "floors_bound", "floors_basis")),
    ("최소 층수", "min_floors", ("min_floors", "min_floors_bound")),
    ("연면적", "max_area", ("max_area", "area_bound")),
    ("접수기간", "apply_end", ("apply_start", "apply_end", "application_period")),
    ("접수기간(원문)", "application_period", ("application_period",)),
    ("공고일", "notice_date", ("notice_date",)),
    ("집합건물 제외", "collective_excluded", ("collective_excluded",)),
    ("공동주택 제외", "multi_housing_excluded", ("multi_housing_excluded",)),
    ("선정방식", "selection_method", ("selection_method",)),
    ("지자체", "local_gov", ("local_gov",)),
    ("사업명", "program_name", ("program_name",)),
    ("연도", "year", ("year",)),
    ("시기", "season", ("season",)),
    ("규모", "scale", ("scale",)),
]
CONFLICT_CHECK = {"min_years", "built_before_year", "max_floors", "max_area", "apply_end"}
LISTS = ("exclusions", "priority_rules", "offmap_conditions", "support_content")
FILTERS = (("use_filter", "용도"), ("structure_filter", "구조"))
CONTACT = ("reception", "inquiry", "apply_method")
# 합친 뒤 다시 계산하는 안내(글마다 붙어 있던 것은 버린다)
RECOMPUTED = ("뉴스·보도자료 출처", "경과연수 조건을 찾지 못했습니다", "지자체를 찾지 못했습니다", "시군구코드로 찾지 못했습니다")


@dataclass
class MergeSource:
    notice: NoticeConditions
    issues: list[str] = field(default_factory=list)
    url: str = ""
    title: str = ""
    year: int | None = None  # 글의 연도(검색 결과 날짜·제목). 공고 날짜가 있으면 그것이 먼저


@dataclass
class Merged:
    notice: NoticeConditions
    issues: list[str]
    sources: list[MergeSource]  # 합친 글(근거의 [출처 n] 순서)
    dropped: list[MergeSource]  # 회차가 달라 뺀 글


def round_year(s: MergeSource) -> int | None:
    n = s.notice
    for d in (n.apply_start, n.apply_end, n.notice_date):
        if isinstance(d, date):
            return d.year
    if n.year and n.year[:4].isdigit():
        return int(n.year[:4])
    return s.year


def _show(v) -> str:
    if isinstance(v, float):
        return f"{v:g}"
    return str(v)


def _group_text(n: NoticeConditions, name: str, fields: tuple[str, ...]) -> str:
    if name == "층수" and n.max_floors is not None:
        return f"{n.max_floors}층 {'이하' if n.floors_bound == 'LE' else '미만'}"
    if name == "연면적" and n.max_area is not None:
        return f"{n.max_area:g}㎡ {'이하' if n.area_bound == 'LE' else '미만'}"
    if name == "접수기간":
        return f"{n.apply_start or '?'}~{n.apply_end or '?'}"
    return _show(getattr(n, fields[0]))


def merge(sources: list[MergeSource]) -> Merged:
    if not sources:
        raise ValueError("합칠 글이 없습니다.")
    years = [y for y in (round_year(s) for s in sources) if y]
    latest = max(years) if years else None
    keep = [s for s in sources if latest is None or round_year(s) in (None, latest)]
    dropped = [s for s in sources if s not in keep]
    keep.sort(key=lambda s: SOURCE_RANK.get(s.notice.source_type, 3))  # 같은 순위는 들어온 순서(안정 정렬)
    idx = {id(s): i + 1 for i, s in enumerate(keep)}
    tag = lambda s: f"[출처 {idx[id(s)]}]"  # noqa: E731

    if len(keep) == 1:  # 한 글이면 그대로(근거 표시만 맞춘다)
        s = keep[0]
        n = s.notice.model_copy(update={"source_urls": [s.url] if s.url else [], "source_url": s.url or s.notice.source_url})
        issues = list(s.issues) + [f"{y}년 글은 올해 회차와 달라 합치지 않았습니다: {d.title or d.url}" for d in dropped for y in [round_year(d)]]
        return Merged(n, issues, keep, dropped)

    primary = keep[0]
    update: dict = {}
    evidence: dict[str, str] = {}
    issues: list[str] = []

    for name, key, fields in GROUPS:
        src = next((s for s in keep if getattr(s.notice, key) is not None), None)
        if src is None:
            continue
        for f in fields:
            update[f] = getattr(src.notice, f)
            ev_key = "max_floors" if f == "max_floors" else "max_area" if f == "max_area" else f
            if ev_key in src.notice.evidence:
                evidence[ev_key] = f"{tag(src)} {src.notice.evidence[ev_key]}"
        if key in CONFLICT_CHECK:
            chosen = _group_text(src.notice, name, fields)
            others = [(s, _group_text(s.notice, name, fields)) for s in keep if s is not src and getattr(s.notice, key) is not None]
            diff = [(s, t) for s, t in others if t != chosen]
            if diff:
                issues.append(
                    f"출처마다 다름 · {name}: {chosen}({tag(src)} 사용) / " + " / ".join(f"{t}({tag(s)})" for s, t in diff) + " — 원문을 확인하세요"
                )
    # years_basis는 기준 연도 묶음에서만 바뀐다. 경과연수가 있으면 경과연수 기준
    if update.get("min_years") is not None:
        update["years_basis"] = "ELAPSED_YEARS"
        update["built_before_year"] = None
        update["built_before_inclusive"] = None

    for f, label in FILTERS:
        src = next((s for s in keep if getattr(s.notice, f)), None)
        update[f] = list(getattr(src.notice, f)) if src else []
        if src:
            if f in src.notice.evidence:
                evidence[f] = f"{tag(src)} {src.notice.evidence[f]}"
            for s in keep:
                other = getattr(s.notice, f)
                if s is not src and other and set(other) != set(update[f]):
                    issues.append(f"출처마다 다름 · {label}: {', '.join(update[f])}({tag(src)} 사용) / {', '.join(other)}({tag(s)})")

    for f in LISTS:
        update[f] = list(dict.fromkeys(x for s in keep for x in getattr(s.notice, f)))
        ev = [f"{tag(s)} {s.notice.evidence[f]}" for s in keep if f in s.notice.evidence]
        if ev:
            evidence[f] = " / ".join(ev)

    contact = {}
    for f in CONTACT:
        src = next((s for s in keep if getattr(s.notice.contact, f)), None)
        contact[f] = getattr(src.notice.contact, f) if src else None
        if src and f"contact.{f}" in src.notice.evidence:
            evidence[f"contact.{f}"] = f"{tag(src)} {src.notice.evidence[f'contact.{f}']}"
    contact["documents"] = list(dict.fromkeys(x for s in keep for x in s.notice.contact.documents))
    update["contact"] = Contact(**contact)

    update["sigungu_codes"] = list(dict.fromkeys(c for s in keep for c in s.notice.sigungu_codes))
    update["source_url"] = primary.url or primary.notice.source_url
    update["source_urls"] = [s.url for s in keep if s.url]
    update["source_type"] = primary.notice.source_type
    update["evidence"] = evidence
    update["reviewed"] = False
    n = NoticeConditions.model_validate({**primary.notice.model_dump(), **{k: v for k, v in update.items() if k != "contact"}, "contact": update["contact"].model_dump()})

    labels = ", ".join(f"{tag(s)} {SOURCE_LABEL.get(s.notice.source_type, '글')}" for s in keep)
    issues.insert(0, f"글 {len(keep)}건을 합쳤습니다({labels}). 값은 앞 출처를 먼저 씁니다")
    for s in keep:
        issues += [f"{tag(s)} {i}" for i in s.issues if not any(r in i for r in RECOMPUTED)]
    issues += [f"{round_year(d)}년 글은 올해 회차와 달라 합치지 않았습니다: {d.title or d.url}" for d in dropped]
    if n.source_type in ("NEWS", "PRESS_RELEASE"):
        issues.insert(0, "뉴스·보도자료 출처입니다. 원문 공고를 확인하세요")
    if n.min_years is None and n.years_basis == "ELAPSED_YEARS":
        issues.append("경과연수 조건을 찾지 못했습니다(판정 때 법정 30년 적용)")
    if not n.sigungu_codes:
        issues.append("공고에서 지자체를 찾지 못했습니다. 적용 시군구를 직접 고르세요")
    return Merged(n, issues, keep, dropped)
