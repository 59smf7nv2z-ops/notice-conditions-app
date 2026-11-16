import { KEYMAP, LIST_KEYS } from "./schema";

export type FieldValue = { value: unknown; evidence: string | null };
export type RawResult = Record<string, unknown>;

export function toList(text: string): string[] {
  return text
    .split(/\n|;|[①-⑳]/)
    .map((p) => p.replace(/^[\s\-·,]+|[\s\-·,]+$/g, ""))
    .filter(Boolean);
}

export function shapeProblems(result: RawResult): string[] {
  const problems: string[] = [];
  for (const k of Object.keys(KEYMAP)) {
    if (!(k in result)) {
      problems.push(`${k} 항목이 없음`);
    } else if (k !== "needs_check") {
      const v = result[k];
      if (!(v && typeof v === "object" && "value" in v && "evidence" in v)) {
        problems.push(`${k} 항목이 {value, evidence} 모양이 아님`);
      }
    }
  }
  return problems;
}

export function normalize(result: RawResult): { fixed: Record<string, FieldValue>; warnings: string[] } {
  const topEv =
    result.evidence && typeof result.evidence === "object" && !Array.isArray(result.evidence)
      ? (result.evidence as Record<string, unknown>)
      : {};
  const fixed: Record<string, FieldValue> = {};
  const shapeWarn: string[] = [];
  for (const [k, v] of Object.entries(result)) {
    if (k === "evidence" && Object.keys(topEv).length) continue;
    if (v && typeof v === "object" && !Array.isArray(v) && "value" in (v as object)) {
      const rec = v as { value: unknown; evidence?: unknown };
      let value = rec.value;
      if (LIST_KEYS.has(k) && typeof value === "string") {
        value = toList(value);
      }
      const ev = rec.evidence;
      fixed[k] = { value, evidence: ev == null ? null : String(ev) };
    } else if (k === "needs_check") {
      fixed[k] = { value: v, evidence: null };
    } else {
      let ev: unknown = topEv[k] ?? topEv[KEYMAP[k] ?? k];
      if (Array.isArray(ev)) ev = ev.map(String).join(" / ");
      let value: unknown = v;
      if (LIST_KEYS.has(k) && typeof value === "string") {
        value = toList(value);
      }
      if (!ev) shapeWarn.push(KEYMAP[k] ?? k);
      fixed[k] = { value, evidence: ev == null ? null : String(ev) };
    }
  }
  const warnings: string[] = [];
  for (const k of Object.keys(fixed)) {
    if (LIST_KEYS.has(k) && typeof (result[k] as { value?: unknown } | undefined)?.value === "string") {
      warnings.push(`'${KEYMAP[k] ?? k}' 항목이 목록이 아니라 글로 와서 나눠 저장합니다.`);
    }
  }
  if (shapeWarn.length) {
    warnings.push(
      `모델이 모양을 다르게 보내 근거(원문 인용)를 못 찾은 항목 ${shapeWarn.length}개: ${shapeWarn.join(", ")}`,
    );
  }
  return { fixed, warnings };
}

export function toKoreanResult(fixed: Record<string, FieldValue>): Record<string, FieldValue> {
  const out: Record<string, FieldValue> = {};
  for (const [k, v] of Object.entries(fixed)) {
    if (k in KEYMAP) out[KEYMAP[k]] = v;
  }
  return out;
}

export function flat(v: unknown): string {
  if (Array.isArray(v)) return v.map(String).join(" / ");
  return v == null ? "" : String(v);
}
