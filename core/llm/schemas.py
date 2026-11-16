"""LLM 출력 스키마(구조화 출력). 판정용 NoticeConditions로 바꾸는 일은 core.llm.extractor가 코드로 한다.

- 모든 항목은 {value, evidence}. 원문에 없으면 value=null, evidence=null.
- 층수·연면적은 숫자로 바꾸지 않고 원문 표현("3층 이하", "연면적 200㎡ 미만")을 받는다.
  이하/미만 해석은 코드(core.conditions.parse_*)가 한다.
- 날짜는 원문 그대로의 날짜만 YYYY-MM-DD로. 마감 여부는 묻지 않는다.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class StrField(BaseModel):
    value: str | None
    evidence: str | None


class IntField(BaseModel):
    value: int | None
    evidence: str | None


class BoolField(BaseModel):
    value: bool | None
    evidence: str | None


class ListField(BaseModel):
    value: list[str]
    evidence: str | None


BusinessTypeName = Literal[
    "APPLY_INSPECTION", "EX_OFFICIO_INSPECTION", "REPAIR_SUPPORT", "MULTI_HOUSING_SUBSIDY", "HOUSING_REDEVELOPMENT", "UNRELATED"
]


class ClassifyOut(BaseModel):
    business_type: BusinessTypeName
    evidence: str | None  # 원문 인용
    reason: str  # 한두 문장
    has_repair_section: bool  # 같은 문서에 보수·보강 지원이 함께 있는지


class ExtractOut(BaseModel):
    local_gov: StrField
    program_name: StrField
    year: StrField
    season: StrField
    notice_date: StrField  # YYYY-MM-DD
    application_period: StrField  # 원문
    apply_start: StrField  # YYYY-MM-DD
    apply_end: StrField  # YYYY-MM-DD
    min_years: IntField  # 사용승인 후 N년 이상
    built_before_year: IntField  # "○○년 이전 사용승인"형
    built_before_inclusive: BoolField  # 그 연도를 포함하는지 원문이 분명할 때만
    floors_text: StrField  # 원문 표현 그대로 예: "3층 이하"
    floors_include_underground: BoolField  # 지하층을 층수에 넣는다고 원문이 분명할 때만 true
    area_text: StrField  # 예: "연면적 200㎡ 미만"
    use_conditions: ListField  # 대상을 제한하는 용도만
    structure_conditions: ListField
    exclusions: ListField
    collective_excluded: BoolField
    multi_housing_excluded: BoolField
    selection_method: StrField  # 심사/선착순/예산소진/직권/기타
    priority_criteria: ListField
    offmap_conditions: ListField  # 대장만으로 판단할 수 없는 조건
    support_content: ListField
    scale: StrField
    reception: StrField  # 접수처
    inquiry: StrField  # 문의처
    apply_method: StrField  # 신청방법
    documents: ListField  # 제출서류
    source_type: Literal["OFFICIAL_NOTICE", "LEAFLET", "PRESS_RELEASE", "NEWS"]
