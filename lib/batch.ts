import { judgeBuilding } from "./compare";
import type { BuildingRecord, ExtractBatch, Extracted, ExtractKind, Verdict } from "./types";

export function makeBatch(items: Extracted[]): ExtractBatch {
  return {
    id: crypto.randomUUID(),
    kind: items.length > 1 ? "묶음" : "단건",
    items,
  };
}

export function batchLabel(batch: ExtractBatch): string {
  if (batch.kind === "단건") return `단건 · ${batch.items[0]?.공고 || "공고"}`;
  const first = batch.items[0]?.공고 || "공고";
  return `묶음 · ${batch.items.length}건 (${first} 외)`;
}

export function kindOf(batch: ExtractBatch | undefined): ExtractKind {
  return batch?.kind === "묶음" ? "묶음" : "단건";
}

export type NoticeMatch = {
  notice: Extracted;
  overall: Verdict;
  judged: Pick<BuildingRecord, "overall" | "checks">;
};

export function partitionNotices(
  items: Extracted[],
  form: Pick<BuildingRecord, "address" | "ageYears" | "floors" | "floorArea" | "use" | "structure"> &
    Partial<Pick<BuildingRecord, "ownerHint" | "approvalDate" | "basementFloors">>,
): { 해당: NoticeMatch[]; 비해당: NoticeMatch[]; 확인필요: NoticeMatch[] } {
  const 해당: NoticeMatch[] = [];
  const 비해당: NoticeMatch[] = [];
  const 확인필요: NoticeMatch[] = [];
  for (const notice of items) {
    const judged = judgeBuilding(notice, form);
    const row: NoticeMatch = { notice, overall: judged.overall, judged };
    if (judged.overall === "해당") 해당.push(row);
    else if (judged.overall === "비해당") 비해당.push(row);
    else 확인필요.push(row);
  }
  return { 해당, 비해당, 확인필요 };
}

export function pickPrimaryMatch(parts: ReturnType<typeof partitionNotices>): NoticeMatch | undefined {
  return parts.해당[0] ?? parts.확인필요[0] ?? parts.비해당[0];
}
