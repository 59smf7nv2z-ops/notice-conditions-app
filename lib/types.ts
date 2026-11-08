export type FieldValue = { value: unknown; evidence: string | null };

export type Extracted = {
  공고: string;
  파일명?: string;
  모델: string;
  결과: Record<string, FieldValue>;
  skipped: string[];
  readText: string;
  mock: boolean;
  warnings: string[];
  error?: string;
};

export type ExtractKind = "단건" | "묶음";

export type ExtractBatch = {
  id: string;
  kind: ExtractKind;
  title: string;
  items: Extracted[];
};

export type Verdict = "해당" | "비해당" | "확인필요";

export type CheckRow = {
  item: string;
  condition: string;
  building: string;
  verdict: Verdict;
  note: string;
};

export type BuildingRecord = {
  id: string;
  address: string;
  ownerHint: string;
  approvalDate?: string;
  ageYears: string;
  floors: string;
  basementFloors?: string;
  floorArea: string;
  use: string;
  structure: string;
  noticeName: string;
  overall: Verdict;
  checks: CheckRow[];
};

export type GuideTone = "elder" | "official" | "sms";

export type TabId = "extract" | "compare" | "report" | "map";

export const TABS: { id: TabId; label: string; short: string }[] = [
  { id: "extract", label: "공고문 분석 & 조건 추출", short: "조건 추출" },
  { id: "compare", label: "건물 정보 대조 & 1차 판정", short: "1차 판정" },
  { id: "report", label: "맞춤형 안내문 및 결과 리포트", short: "안내문" },
  { id: "map", label: "지역별 노후건축물 현황 지도", short: "현황 지도" },
];
