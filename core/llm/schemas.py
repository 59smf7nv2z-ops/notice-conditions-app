"""LLM 출력 스키마(구조화 출력). 판정용 NoticeConditions로 바꾸는 일은 core.llm.extractor가 코드로 한다.

- 모든 항목은 {value, evidence}. 원문에 없으면 value=null, evidence=null.
- 층수·연면적은 숫자로 바꾸지 않고 원문 표현("3층 이하", "연면적 200㎡ 미만")을 받는다.
  이하/미만 해석은 코드(core.conditions.parse_*)가 한다.
- 날짜는 원문 그대로의 날짜만 YYYY-MM-DD로. 마감 여부는 묻지 않는다.
- confidence(high/medium/low)와 fallback_reason(): 값이 있으면 core.llm.fallback이 상위 모델로 다시 한다.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, create_model


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


Confidence = Literal["high", "medium", "low"]


class ClassifyOut(BaseModel):
    business_type: BusinessTypeName
    evidence: str | None  # 원문 핵심 구절(서술형 이유는 받지 않는다: 출력 토큰 절약)
    has_repair_section: bool  # 같은 문서에 보수·보강 지원이 함께 있는지
    confidence: Confidence  # low면 상위 모델로 다시 한다

    def fallback_reason(self) -> str | None:
        return "분류 확신 낮음" if self.confidence == "low" else None


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
    confidence: Confidence  # 글자가 흐리거나 조건을 해석하기 애매하면 low

    def fallback_reason(self) -> str | None:
        """상위 모델로 다시 할 이유. 모델 자기 평가(low) + 핵심 조건이 하나도 없는 경우."""
        if self.confidence == "low":
            return "추출 확신 낮음"
        core = (self.min_years.value, self.built_before_year.value, self.floors_text.value, self.area_text.value)
        if all(v is None for v in core) and not self.use_conditions.value and not self.structure_conditions.value:
            return "핵심 조건(경과연수·층수·연면적·용도·구조)을 하나도 찾지 못함"
        return None


class _AnalyzeBase(BaseModel):
    def fallback_reason(self) -> str | None:
        if self.confidence == "low":
            return "확신 낮음"
        if self.business_type == "APPLY_INSPECTION":
            return ExtractOut.fallback_reason(self)
        return None


# 분류 + 추출을 한 번에(문서 입력 토큰을 한 번만 낸다). 분류 항목을 앞에 둬서 모델이 먼저 정하게 한다.
# 출력 스키마가 다르면 프롬프트 캐시가 이어지지 않아(2026-11-17 확인) 두 번 부르는 것보다 싸다.
AnalyzeOut = create_model(
    "AnalyzeOut",
    __base__=_AnalyzeBase,
    business_type=(BusinessTypeName, ...),
    business_evidence=(str | None, ...),
    has_repair_section=(bool, ...),
    **{k: (f.annotation, ...) for k, f in ExtractOut.model_fields.items()},
)
