export const MODEL = "claude-sonnet-5-5";
export const MAX_TOKENS = 4096;
export const MIN_TEXT = 150;
export const MAX_FILES = 8;
export const MAX_FILE_BYTES = 8 * 1024 * 1024;
export const MAX_TOTAL_BYTES = 16 * 1024 * 1024;
export const MAX_INFLATE_BYTES = 8 * 1024 * 1024;
export const MAX_ZIP_UNCOMPRESSED = 16 * 1024 * 1024;

export const IMAGE_TYPES: Record<string, string> = {
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg",
  ".webp": "image/webp",
};

export const SYSTEM_PROMPT = `너는 지자체 '소규모 노후 건축물 안전점검' 공고문에서 지원 조건을 뽑는 도우미다.
입력은 공고문(글 또는 이미지) 한 건이며, 여러 장의 이미지가 한 공고의 앞뒤 면일 수 있다.
반드시 record_notice 도구로 결과를 제출하라. 규칙:
1. 원문에 없는 내용은 값을 null 로 둔다. 추측해서 채우지 않는다.
2. 값을 채운 항목은 evidence 에 원문 문장(또는 표의 해당 칸 내용)을 그대로 인용한다. 근거가 없으면 값도 null.
3. '이하/미만/이상/초과'는 원문 그대로 보존한다. 층수는 "3층 이하", 연면적은 "1000㎡ 이하"처럼 쓴다(쉼표 없이 숫자).
4. 경과연수는 숫자(년)만 쓴다. 예: 사용승인 후 30년 경과 -> 30.
5. 건축물대장만으로 판단할 수 없는 조건(위원회 심사, 민원, 위험도 평가, 현장 확인 등)은 needs_check(확인필요) 목록에 따로 적는다.
6. 사업유형은 신청자가 신청하는 방식이면 '신청형', 지자체가 직접 대상을 정해 점검하면 '직권형', 그 외 '기타'.
7. 연도나 지자체명이 문서에 없으면 null 이다. 전화번호 국번 등으로 짐작하지 않는다.
8. 선정방식(selection_method)은 정해진 분류 중에서만 고른다. 선정 기준의 세부 내용(노후도, 민원, 위험도 등)은 priority_criteria 에 적는다.
   분류 정의: 심사 = 노후도·위험도·민원 등 기준을 보고 지자체가 대상을 골라 선정, 선착순 = 접수 순서대로,
   예산소진 = 예산이 다할 때까지 접수, 직권 = 지자체가 신청 없이 대상을 정함, 기타 = 위에 해당하지 않음.
9. 용도조건(use_conditions)은 '이런 용도만 신청 가능'처럼 대상을 제한하는 경우만 적는다. '~ 우선 지원'은 priority_criteria 이다.`;

function field(valueSchema: object, desc: string) {
  return {
    type: "object",
    description: desc,
    properties: {
      value: valueSchema,
      evidence: { anyOf: [{ type: "string" }, { type: "null" }], description: "원문 인용. 값이 null 이면 null" },
    },
    required: ["value", "evidence"],
  };
}

const STR = { anyOf: [{ type: "string" }, { type: "null" }] };
const NUM = { anyOf: [{ type: "number" }, { type: "null" }] };
const LIST = { anyOf: [{ type: "array", items: { type: "string" } }, { type: "null" }] };

export const KEYMAP: Record<string, string> = {
  local_gov: "지자체",
  program_name: "사업명",
  year: "연도",
  season: "시기",
  program_type: "사업유형",
  min_age_years: "경과연수",
  max_floors: "층수",
  max_floor_area: "연면적",
  use_conditions: "용도조건",
  structure_conditions: "구조조건",
  exclusions: "제외대상",
  selection_method: "선정방식",
  priority_criteria: "우선순위기준",
  scale: "규모",
  application_period: "접수기간",
  eligibility_method: "신청자격방법",
  support_content: "지원내용",
  needs_check: "확인필요",
};

export const KEY_ORDER = Object.keys(KEYMAP);

export const LIST_KEYS = new Set([
  "use_conditions",
  "structure_conditions",
  "exclusions",
  "priority_criteria",
  "support_content",
]);

export const TOOL = {
  name: "record_notice",
  description: "공고문에서 뽑은 지원 조건을 기록한다. 각 항목은 value(값)와 evidence(원문 인용)로 구성된다.",
  input_schema: {
    type: "object",
    properties: {
      local_gov: field(STR, "지자체. 예: 대전광역시 중구"),
      program_name: field(STR, "사업명. 공고 제목 또는 사업 이름"),
      year: field(STR, "연도. 예: 2026"),
      season: field(STR, "시기. 예: 하반기"),
      program_type: field(
        { anyOf: [{ type: "string", enum: ["신청형", "직권형", "기타"] }, { type: "null" }] },
        "사업유형: 신청형/직권형/기타",
      ),
      min_age_years: field(NUM, "경과연수. 사용승인 후 경과 년수(숫자)"),
      max_floors: field(STR, "층수. 예: 3층 이하"),
      max_floor_area: field(STR, "연면적. 예: 1000㎡ 이하"),
      use_conditions: field(
        LIST,
        "용도조건. 신청 대상을 제한하는 용도만. 예: 주택, 제1·2종 근린생활시설. 용도 제한이 없으면 null 또는 빈 목록. '우선' 지원 용도는 여기 넣지 말고 priority_criteria 에 적는다",
      ),
      structure_conditions: field(LIST, "구조조건. 예: 목조, 조적조"),
      exclusions: field(LIST, "제외대상. 신청에서 제외되는 건축물 목록(원문 표현대로)"),
      selection_method: field(
        {
          anyOf: [{ type: "string", enum: ["심사", "선착순", "예산소진", "직권", "기타"] }, { type: "null" }],
        },
        "선정방식 분류. 원문에 선정 방식이 명시된 경우만: 심사/선착순/예산소진('예산 소진 시까지')/직권/기타. 없으면 null. 세부 기준은 priority_criteria 에 적는다",
      ),
      priority_criteria: field(
        LIST,
        "우선순위기준. 우선 지원하는 기준과 선정 때 고려하는 요소. 예: 주택 포함 건축물, 노후도, 민원, 위험도",
      ),
      scale: field(STR, "규모. 지원 규모. 예: 10개소"),
      application_period: field(STR, "접수기간. 신청 기간 원문"),
      eligibility_method: field(STR, "신청자격방법. 신청 자격과 방법 원문 요약"),
      support_content: field(LIST, "지원내용. 무료 점검, 컨설팅, 보수비 지원 등"),
      needs_check: {
        type: "array",
        items: { type: "string" },
        description: "확인필요. 건축물대장만으로 판단할 수 없는 조건",
      },
    },
    required: KEY_ORDER,
  },
};

export const SUBMIT_HINT =
  "위 공고에서 조건을 뽑아 record_notice 도구를 호출해 제출하라. 글로 답하지 말고 반드시 도구를 호출하라. 모든 항목을 {value, evidence} 모양으로 채워라.";
