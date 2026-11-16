import { judgeBuilding } from "./compare";
import { flat } from "./download";
import { matchSido, type SidoRegion } from "./korea-sido";
import { SAMPLE_BUILDINGS } from "./registry";
import type { BuildingRecord, ExtractBatch, Extracted, Verdict } from "./types";
import sampleExtract from "./sample-extract.json";

const DONG_COORDS: Record<string, [number, number]> = {
  은행동: [36.3286, 127.4314],
  둔산동: [36.351, 127.3776],
  선화동: [36.3278, 127.4203],
};

function hashOffset(seed: string): [number, number] {
  let h = 0;
  for (let i = 0; i < seed.length; i++) h = (h * 31 + seed.charCodeAt(i)) | 0;
  const a = ((h % 17) - 8) * 0.0022;
  const b = ((((h / 17) | 0) % 17) - 8) * 0.0022;
  return [a, b];
}

export function geocodeAddress(address: string): [number, number] | null {
  const raw = address.trim();
  if (!raw) return null;
  for (const [dong, coord] of Object.entries(DONG_COORDS)) {
    if (raw.includes(dong)) {
      const [dlat, dlng] = hashOffset(raw);
      return [coord[0] + dlat, coord[1] + dlng];
    }
  }
  const sido = matchSido(raw);
  if (!sido) return null;
  const [dlat, dlng] = hashOffset(raw);
  return [sido.center[0] + dlat, sido.center[1] + dlng];
}

export function noticesOfBatches(batches: ExtractBatch[]): Extracted[] {
  return batches.flatMap((b) => b.items);
}

export function sidoIdsWithNotices(notices: Extracted[]): Set<string> {
  const ids = new Set<string>();
  for (const n of notices) {
    const text = `${n.공고} ${flat(n.결과["지자체"]?.value)}`;
    const sido = matchSido(text);
    if (sido) ids.add(sido.id);
  }
  return ids;
}

export type MapPin = {
  id: string;
  lat: number;
  lng: number;
  address: string;
  overall: Verdict;
  noticeName: string;
  sample: boolean;
};

function asPin(b: BuildingRecord, sample: boolean): MapPin | null {
  const coord = geocodeAddress(b.address);
  if (!coord) return null;
  return {
    id: b.id,
    lat: coord[0],
    lng: coord[1],
    address: b.address,
    overall: b.overall,
    noticeName: b.noticeName,
    sample,
  };
}

function samplePin(notice: Extracted, kind: Verdict): MapPin | null {
  const fill = SAMPLE_BUILDINGS[kind];
  const judged = judgeBuilding(notice, fill);
  return asPin(
    {
      id: `sample-${kind}`,
      ...fill,
      noticeName: notice.공고,
      ...judged,
    },
    true,
  );
}

export function collectMapPins(
  buildings: BuildingRecord[],
  liveMatch: BuildingRecord | null,
  notices: Extracted[],
): { pins: MapPin[]; usedSamples: boolean } {
  const seen = new Set<string>();
  const pins: MapPin[] = [];
  const rows = [...buildings];
  if (liveMatch && !rows.some((b) => b.address === liveMatch.address && b.overall === liveMatch.overall)) {
    rows.unshift(liveMatch);
  }
  for (const b of rows) {
    const pin = asPin(b, false);
    if (!pin) continue;
    const key = pin.address + pin.overall;
    if (seen.has(key)) continue;
    seen.add(key);
    pins.push(pin);
  }
  const notice = notices[0] ?? (sampleExtract as Extracted);
  const have = new Set(pins.map((p) => p.overall));
  let usedSamples = pins.length === 0;
  for (const v of ["해당", "비해당", "확인필요"] as Verdict[]) {
    if (have.has(v)) continue;
    const extra = samplePin(notice, v);
    if (!extra) continue;
    pins.push(extra);
    usedSamples = true;
  }
  return { pins, usedSamples };
}

export function regionHasNotice(region: SidoRegion, colored: Set<string>): boolean {
  return colored.has(region.id);
}
