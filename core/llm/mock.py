"""키가 없을 때 쓰는 MockProvider. grok 앱의 '키가 없으면 샘플 결과' 동작을 유지한다.

외부로 아무것도 보내지 않는다. 결과는 화면 확인용 샘플(대전 중구, 가상)이다.
"""

from __future__ import annotations

from core.llm.base import Part, T, Usage
from core.llm.schemas import (
    AnalyzeOut,
    BoolField,
    ClassifyOut,
    ExtractOut,
    IntField,
    ListField,
    StrField,
)


def _s(v, ev):
    return StrField(value=v, evidence=ev if v is not None else None)


def sample_extract() -> ExtractOut:
    return ExtractOut(
        local_gov=_s("대전광역시 중구", "대전광역시 중구는 2026년 하반기 소규모 노후 건축물 안전점검 사업을 시행한다."),
        program_name=_s("소규모 노후 건축물 안전점검(샘플)", "소규모 노후 건축물 안전점검 사업을 시행한다."),
        year=_s("2026", "2026년 하반기"),
        season=_s("하반기", "2026년 하반기"),
        notice_date=_s(None, None),
        application_period=_s("2026. 7. 1. ~ 2026. 7. 31.", "접수기간은 2026. 7. 1.부터 2026. 7. 31.까지로 한다."),
        apply_start=_s("2026-07-01", "2026. 7. 1."),
        apply_end=_s("2026-07-31", "2026. 7. 31."),
        min_years=IntField(value=30, evidence="사용승인 후 30년 경과"),
        built_before_year=IntField(value=None, evidence=None),
        built_before_inclusive=BoolField(value=None, evidence=None),
        floors_text=_s("3층 이하", "3층 이하"),
        floors_include_underground=BoolField(value=None, evidence=None),
        area_text=_s("연면적 1000㎡ 이하", "연면적 1000㎡ 이하"),
        use_conditions=ListField(value=["주택", "제1·2종 근린생활시설"], evidence="주택 및 제1·2종 근린생활시설"),
        structure_conditions=ListField(value=["목조", "조적조"], evidence="목조·조적조"),
        exclusions=ListField(value=["공공건축물", "위험시설로 지정된 건축물"], evidence="공공건축물 및 위험시설로 지정된 건축물은 제외한다."),
        collective_excluded=BoolField(value=None, evidence=None),
        multi_housing_excluded=BoolField(value=None, evidence=None),
        selection_method=_s("선착순", "선착순 접수"),
        priority_criteria=ListField(value=["노후도", "민원", "위험도"], evidence="노후도, 민원, 위험도를 고려한다."),
        offmap_conditions=ListField(value=["현장 확인", "위원회 심사"], evidence="현장 확인 및 위원회 심사가 필요할 수 있다."),
        support_content=ListField(value=["무료 안전점검", "컨설팅"], evidence="무료 안전점검 및 컨설팅"),
        scale=_s("10개소", "10개소"),
        reception=_s("중구청 건축과", "접수처: 중구청 건축과"),
        inquiry=_s("건축과 042-000-0000", "문의: 건축과 042-000-0000"),
        apply_method=_s("방문 또는 온라인 신청", "건축물 소유자가 방문 또는 온라인으로 신청한다."),
        documents=ListField(value=["신청서", "건축물대장"], evidence="제출서류: 신청서, 건축물대장"),
        source_type="OFFICIAL_NOTICE",
        confidence="high",
    )


class MockProvider:
    name = "mock"

    def __init__(self, model: str = "mock", reason: str = ""):
        self.model = model or "mock"
        self.reason = reason

    def generate_json(self, system: str, parts: list[Part], schema: type[T]) -> tuple[T, Usage]:
        usage = Usage(self.name, self.model)
        if schema is ClassifyOut:
            # 본문이 있는 텍스트 조각(HWP·HWPX 변환문)의 앞부분을 근거 자리에 둔다
            text = next((p.text.split("\n", 1)[1] for p in parts if p.text and "\n" in p.text), "")
            snippet = " ".join(text.split())[:80] or None
            return ClassifyOut(business_type="APPLY_INSPECTION", evidence=snippet, has_repair_section=False, confidence="high"), usage
        if schema is ExtractOut:
            return sample_extract(), usage
        if schema is AnalyzeOut:
            return AnalyzeOut(business_type="APPLY_INSPECTION", business_evidence=None, has_repair_section=False, **sample_extract().model_dump()), usage
        raise NotImplementedError(f"MockProvider: {schema.__name__} 샘플 없음")

    def generate_text(self, system: str, prompt: str) -> tuple[str, Usage]:
        from core.letters import BUILTIN

        tone = "official"
        for t, label in (("elder", "어르신"), ("sms", "문자")):
            if label in prompt:
                tone = t
        return BUILTIN[tone], Usage(self.name, self.model)
