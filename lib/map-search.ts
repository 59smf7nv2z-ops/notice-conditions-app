import { partitionNotices, pickPrimaryMatch } from "./batch";
import { geocodeAddress, type MapPin } from "./map-model";
import { mockRegistryLookup } from "./registry";
import type { Extracted, Verdict } from "./types";

function norm(s: string): string {
  return s.replace(/\s+/g, "").toLowerCase();
}

export type SearchHit = {
  pin: MapPin;
  source: "match" | "mock";
  label: string;
};

function pinFromJudge(address: string, lat: number, lng: number, notices: Extracted[], source: "match" | "mock"): SearchHit {
  const fill = mockRegistryLookup(address) ?? {
    address,
    ownerHint: "",
    approvalDate: "",
    ageYears: "",
    floors: "",
    basementFloors: "",
    floorArea: "",
    use: "",
    structure: "",
  };
  const notice = notices[0];
  const parts = partitionNotices(notices, fill);
  const primary = pickPrimaryMatch(parts);
  const overall: Verdict = primary?.overall ?? "확인필요";
  return {
    source,
    label: address,
    pin: {
      id: `search-${norm(address).slice(0, 40)}`,
      lat,
      lng,
      address: fill.address || address,
      overall,
      noticeName: primary?.notice.공고 ?? notice?.공고 ?? "공고",
      sample: source === "mock",
    },
  };
}

export function matchExistingPin(query: string, pins: MapPin[]): MapPin | undefined {
  const n = norm(query);
  if (!n) return undefined;
  return pins.find((p) => {
    const a = norm(p.address);
    return a.includes(n) || n.includes(a);
  });
}

export async function searchMapAddress(query: string, pins: MapPin[], notices: Extracted[]): Promise<SearchHit | { error: string }> {
  const q = query.trim();
  if (q.length < 2) return { error: "주소를 2자 이상 입력해 주세요." };

  const existing = matchExistingPin(q, pins);
  if (existing) {
    return { pin: existing, source: existing.sample ? "mock" : "match", label: existing.address };
  }

  let lat: number | null = null;
  let lng: number | null = null;
  let label = q;
  try {
    const res = await fetch(`/api/geocode?q=${encodeURIComponent(q)}`);
    const body = (await res.json()) as { lat?: number; lng?: number; label?: string; error?: string };
    if (res.ok && Number.isFinite(body.lat) && Number.isFinite(body.lng)) {
      lat = body.lat as number;
      lng = body.lng as number;
      label = body.label || q;
    }
  } catch {
    /* fallback below */
  }
  if (lat == null || lng == null) {
    const local = geocodeAddress(q);
    if (!local) return { error: "해당 주소를 지도에서 찾지 못했습니다. 시·군·구를 포함해 입력해 주세요." };
    lat = local[0];
    lng = local[1];
  }
  return pinFromJudge(label, lat, lng, notices, "mock");
}
