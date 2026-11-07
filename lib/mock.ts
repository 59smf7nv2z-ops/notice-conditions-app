import type { RawResult } from "./normalize";

export function mockRecord(readText: string, name: string): RawResult {
  const snippet = readText.replace(/\s+/g, " ").slice(0, 80) || `${name} 샘플 원문`;
  const confirm = /확인/.test(name);
  const strict = /비해당|엄격/.test(name);
  return {
    local_gov: { value: "대전광역시 중구", evidence: snippet },
    program_name: { value: "소규모 노후 건축물 안전점검", evidence: snippet },
    year: { value: "2026", evidence: snippet },
    season: { value: "하반기", evidence: snippet },
    program_type: { value: "신청형", evidence: snippet },
    min_age_years: confirm
      ? { value: "", evidence: null }
      : { value: strict ? 80 : 30, evidence: strict ? "사용승인 후 80년 경과" : "사용승인 후 30년 경과" },
    max_floors: { value: "3층 이하", evidence: "3층 이하" },
    max_floor_area: { value: "1000㎡ 이하", evidence: "연면적 1000㎡ 이하" },
    use_conditions: { value: ["주택", "제1·2종 근린생활시설"], evidence: snippet },
    structure_conditions: { value: ["목조", "조적조"], evidence: snippet },
    exclusions: { value: ["공공건축물", "위험시설로 지정된 건축물"], evidence: snippet },
    selection_method: { value: "선착순", evidence: "선착순 접수" },
    priority_criteria: { value: ["노후도", "민원", "위험도"], evidence: snippet },
    scale: { value: "10개소", evidence: "10개소" },
    application_period: { value: "2026. 7. 1. ~ 2026. 7. 31.", evidence: snippet },
    eligibility_method: { value: "건축물 소유자가 방문 또는 온라인 신청", evidence: snippet },
    support_content: { value: ["무료 안전점검", "컨설팅"], evidence: snippet },
    needs_check: ["현장 확인", "위원회 심사"],
  };
}
