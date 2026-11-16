import { json } from "../../../lib/http";
import { clientIp } from "../../../lib/rate-limit";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const WINDOW_MS = 10 * 60 * 1000;
const PER_IP = 30;
const hits = new Map<string, number[]>();

function allow(ip: string): boolean {
  const now = Date.now();
  const next = (hits.get(ip) ?? []).filter((t) => now - t < WINDOW_MS);
  if (next.length >= PER_IP) {
    hits.set(ip, next);
    return false;
  }
  next.push(now);
  hits.set(ip, next);
  return true;
}

export async function GET(request: Request) {
  if (!allow(clientIp(request))) {
    return json({ error: "주소 검색이 잠시 많습니다. 조금 뒤 다시 시도해 주세요." }, 429);
  }
  const q = new URL(request.url).searchParams.get("q")?.trim() ?? "";
  if (q.length < 2 || q.length > 200) {
    return json({ error: "주소를 2자 이상 입력해 주세요." }, 400);
  }

  const url = new URL("https://nominatim.openstreetmap.org/search");
  url.searchParams.set("q", q);
  url.searchParams.set("format", "json");
  url.searchParams.set("countrycodes", "kr");
  url.searchParams.set("limit", "1");
  url.searchParams.set("addressdetails", "0");

  try {
    const res = await fetch(url, {
      headers: { "user-agent": "notice-conditions/1.0 (municipal dashboard)", accept: "application/json" },
      signal: AbortSignal.timeout(8000),
    });
    if (!res.ok) return json({ error: "주소 검색 서비스에 잠시 연결하지 못했습니다." }, 502);
    const rows = (await res.json()) as { lat?: string; lon?: string; display_name?: string }[];
    const hit = rows[0];
    const lat = Number(hit?.lat);
    const lng = Number(hit?.lon);
    if (!Number.isFinite(lat) || !Number.isFinite(lng)) {
      return json({ error: "해당 주소를 지도에서 찾지 못했습니다." }, 404);
    }
    return json({ lat, lng, label: hit?.display_name || q });
  } catch {
    return json({ error: "주소 검색 서비스에 잠시 연결하지 못했습니다." }, 502);
  }
}
