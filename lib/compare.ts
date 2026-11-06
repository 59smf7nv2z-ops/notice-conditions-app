import type { BuildingRecord, CheckRow, Extracted, Verdict } from "./types";
import { flat } from "./download";

type Bound = { n: number; op: "le" | "lt" | "ge" | "gt" };

function parseBound(raw: string): Bound | null {
  const t = raw.replace(/,/g, "").replace(/㎡|m²|m2|제곱미터/gi, "");
  const m = t.match(/([\d.]+)\s*(이하|미만|이상|초과)/);
  if (m) {
    const n = Number(m[1]);
    const op = ({ 이하: "le", 미만: "lt", 이상: "ge", 초과: "gt" } as const)[m[2] as "이하"];
    return Number.isFinite(n) ? { n, op } : null;
  }
  const nOnly = t.match(/([\d.]+)/);
  if (!nOnly) return null;
  const n = Number(nOnly[1]);
  return Number.isFinite(n) ? { n, op: "le" } : null;
}

function cmp(value: number, bound: Bound): boolean {
  if (bound.op === "le") return value <= bound.n;
  if (bound.op === "lt") return value < bound.n;
  if (bound.op === "ge") return value >= bound.n;
  return value > bound.n;
}

function num(s: string): number | null {
  const n = Number(String(s).replace(/,/g, "").trim());
  return Number.isFinite(n) && String(s).trim() !== "" ? n : null;
}

function includesAny(hay: string, needles: string[]): boolean {
  const h = hay.replace(/\s+/g, "");
  return needles.some((n) => n && h.includes(n.replace(/\s+/g, "")));
}

function rollup(rows: CheckRow[]): Verdict {
  if (rows.some((r) => r.verdict === "비해당")) return "비해당";
  if (rows.some((r) => r.verdict === "확인필요")) return "확인필요";
  return "해당";
}

export function judgeBuilding(
  notice: Extracted,
  input: Omit<BuildingRecord, "id" | "noticeName" | "overall" | "checks">,
): Pick<BuildingRecord, "overall" | "checks"> {
  const r = notice.결과;
  const checks: CheckRow[] = [];

  const minAge = r["경과연수"]?.value;
  const age = num(input.ageYears);
  if (minAge == null || minAge === "") {
    checks.push({
      item: "경과연수",
      condition: "공고에 없음",
      building: input.ageYears || "—",
      verdict: "확인필요",
      note: "공고에 경과연수 조건이 없어 대장만으로 확정할 수 없습니다.",
    });
  } else if (age == null) {
    checks.push({
      item: "경과연수",
      condition: String(minAge) + "년 이상",
      building: "미입력",
      verdict: "확인필요",
      note: "건축물대장 경과연수를 입력해 주세요.",
    });
  } else {
    const ok = age >= Number(minAge);
    checks.push({
      item: "경과연수",
      condition: `${minAge}년 이상`,
      building: `${age}년`,
      verdict: ok ? "해당" : "비해당",
      note: ok ? "사용승인 후 경과 년수가 기준을 충족합니다." : "경과 년수가 기준에 미달합니다.",
    });
  }

  const floorCond = flat(r["층수"]?.value);
  const floors = num(input.floors);
  if (!floorCond) {
    checks.push({
      item: "층수",
      condition: "공고에 없음",
      building: input.floors || "—",
      verdict: "확인필요",
      note: "층수 제한이 공고에 명시되지 않았습니다.",
    });
  } else if (floors == null) {
    checks.push({
      item: "층수",
      condition: floorCond,
      building: "미입력",
      verdict: "확인필요",
      note: "지상 층수를 입력해 주세요.",
    });
  } else {
    const b = parseBound(floorCond);
    const ok = b ? cmp(floors, b) : true;
    checks.push({
      item: "층수",
      condition: floorCond,
      building: `${floors}층`,
      verdict: b ? (ok ? "해당" : "비해당") : "확인필요",
      note: b ? (ok ? "층수 기준을 충족합니다." : "층수 기준을 벗어납니다.") : "층수 문구를 해석하지 못했습니다.",
    });
  }

  const areaCond = flat(r["연면적"]?.value);
  const area = num(input.floorArea);
  if (!areaCond) {
    checks.push({
      item: "연면적",
      condition: "공고에 없음",
      building: input.floorArea || "—",
      verdict: "확인필요",
      note: "연면적 제한이 공고에 명시되지 않았습니다.",
    });
  } else if (area == null) {
    checks.push({
      item: "연면적",
      condition: areaCond,
      building: "미입력",
      verdict: "확인필요",
      note: "연면적(㎡)을 입력해 주세요.",
    });
  } else {
    const b = parseBound(areaCond);
    const ok = b ? cmp(area, b) : true;
    checks.push({
      item: "연면적",
      condition: areaCond,
      building: `${area}㎡`,
      verdict: b ? (ok ? "해당" : "비해당") : "확인필요",
      note: b ? (ok ? "연면적 기준을 충족합니다." : "연면적 기준을 벗어납니다.") : "연면적 문구를 해석하지 못했습니다.",
    });
  }

  const uses = Array.isArray(r["용도조건"]?.value) ? (r["용도조건"].value as string[]) : [];
  if (!uses.length) {
    checks.push({
      item: "용도",
      condition: "용도 제한 없음",
      building: input.use || "—",
      verdict: "해당",
      note: "공고에 신청 용도 제한이 없습니다.",
    });
  } else if (!input.use.trim()) {
    checks.push({
      item: "용도",
      condition: uses.join(" / "),
      building: "미입력",
      verdict: "확인필요",
      note: "주용도를 입력해 주세요.",
    });
  } else {
    const ok = includesAny(input.use, uses);
    checks.push({
      item: "용도",
      condition: uses.join(" / "),
      building: input.use,
      verdict: ok ? "해당" : "비해당",
      note: ok ? "용도 조건에 포함됩니다." : "용도 조건에 해당하지 않습니다.",
    });
  }

  const structs = Array.isArray(r["구조조건"]?.value) ? (r["구조조건"].value as string[]) : [];
  if (!structs.length) {
    checks.push({
      item: "구조",
      condition: "구조 제한 없음",
      building: input.structure || "—",
      verdict: "해당",
      note: "공고에 구조 제한이 없습니다.",
    });
  } else if (!input.structure.trim()) {
    checks.push({
      item: "구조",
      condition: structs.join(" / "),
      building: "미입력",
      verdict: "확인필요",
      note: "구조를 입력해 주세요.",
    });
  } else {
    const ok = includesAny(input.structure, structs);
    checks.push({
      item: "구조",
      condition: structs.join(" / "),
      building: input.structure,
      verdict: ok ? "해당" : "비해당",
      note: ok ? "구조 조건에 포함됩니다." : "구조 조건에 해당하지 않습니다.",
    });
  }

  const exclusions = Array.isArray(r["제외대상"]?.value) ? (r["제외대상"].value as string[]) : [];
  if (exclusions.length && (includesAny(input.use, exclusions) || includesAny(input.address, exclusions))) {
    checks.push({
      item: "제외대상",
      condition: exclusions.join(" / "),
      building: input.use || input.address,
      verdict: "비해당",
      note: "제외대상 표현과 겹칩니다. 원문을 확인해 주세요.",
    });
  } else {
    checks.push({
      item: "제외대상",
      condition: exclusions.length ? exclusions.join(" / ") : "명시 없음",
      building: "해당 없음으로 입력",
      verdict: exclusions.length ? "확인필요" : "해당",
      note: exclusions.length
        ? "제외대상은 대장 항목만으로 단정하기 어렵습니다."
        : "공고에 제외대상이 없습니다.",
    });
  }

  const needs = r["확인필요"]?.value;
  const needList = Array.isArray(needs) ? needs.map(String) : needs ? [String(needs)] : [];
  if (needList.length) {
    checks.push({
      item: "확인필요",
      condition: needList.join(" / "),
      building: "건축물대장 외 확인",
      verdict: "확인필요",
      note: "위원회·현장·민원 등 대장만으로 판단할 수 없는 조건입니다.",
    });
  }

  return { checks, overall: rollup(checks) };
}
