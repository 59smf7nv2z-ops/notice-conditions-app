export type RegistryFill = {
  address: string;
  ownerHint: string;
  approvalDate: string;
  ageYears: string;
  floors: string;
  basementFloors: string;
  floorArea: string;
  use: string;
  structure: string;
};

export function yearsSince(iso: string, now = new Date()): string {
  if (!iso.trim()) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  let y = now.getFullYear() - d.getFullYear();
  const m = now.getMonth() - d.getMonth();
  if (m < 0 || (m === 0 && now.getDate() < d.getDate())) y -= 1;
  return String(Math.max(0, y));
}

export function withAge(fill: Omit<RegistryFill, "ageYears"> & { ageYears?: string }): RegistryFill {
  return { ...fill, ageYears: fill.ageYears || yearsSince(fill.approvalDate) };
}

/** Mock 건축물대장: 주소 키워드로 샘플 대장을 돌려 줍니다. */
export function mockRegistryLookup(query: string): RegistryFill | null {
  const q = query.replace(/\s+/g, "");
  if (!q) return null;
  if (/공장|산업|신축|둔산/.test(q)) {
    return withAge({
      address: query.trim(),
      ownerHint: "모의대장",
      approvalDate: "2020-04-02",
      floors: "5",
      basementFloors: "1",
      floorArea: "1800",
      use: "공장",
      structure: "철근콘크리트",
    });
  }
  if (/미입력|확인|수동/.test(q)) {
    return withAge({
      address: query.trim(),
      ownerHint: "모의대장",
      approvalDate: "",
      floors: "2",
      basementFloors: "",
      floorArea: "400",
      use: "",
      structure: "",
    });
  }
  return withAge({
    address: query.trim() || "대전광역시 중구 은행동 12-3",
    ownerHint: "모의대장",
    approvalDate: "1990-03-15",
    floors: "2",
    basementFloors: "0",
    floorArea: "280",
    use: "주택",
    structure: "조적조",
  });
}

export const SAMPLE_BUILDINGS: Record<"해당" | "비해당" | "확인필요", RegistryFill> = {
  해당: withAge({
    address: "대전광역시 중구 은행동 12-3",
    ownerHint: "샘플·적합",
    approvalDate: "1990-03-15",
    floors: "2",
    basementFloors: "0",
    floorArea: "280",
    use: "주택",
    structure: "조적조",
  }),
  비해당: withAge({
    address: "대전광역시 중구 둔산동 88 공장",
    ownerHint: "샘플·불적합",
    approvalDate: "2020-04-02",
    floors: "5",
    basementFloors: "1",
    floorArea: "1800",
    use: "공장",
    structure: "철근콘크리트",
  }),
  확인필요: withAge({
    address: "대전광역시 중구 선화동 3-1 (용도 미기재)",
    ownerHint: "샘플·수동검토",
    approvalDate: "",
    floors: "2",
    basementFloors: "",
    floorArea: "400",
    use: "",
    structure: "",
  }),
};
