const WINDOW_MS = 10 * 60 * 1000;
const PER_IP = 8;
const GLOBAL = 40;
const CONCURRENT_IP = 2;
const CONCURRENT_GLOBAL = 6;

type Bucket = { hits: number[]; inFlight: number };

const byIp = new Map<string, Bucket>();
let globalHits: number[] = [];
let globalInFlight = 0;

function prune(hits: number[], now: number): number[] {
  return hits.filter((t) => now - t < WINDOW_MS);
}

function retryAfterSec(hits: number[], limit: number, now: number): number {
  if (hits.length < limit) return 1;
  const oldest = hits[hits.length - limit];
  return Math.max(1, Math.ceil((WINDOW_MS - (now - oldest)) / 1000));
}

export function clientIp(request: Request): string {
  const forwarded = request.headers.get("x-forwarded-for");
  if (forwarded) {
    const first = forwarded.split(",")[0].trim();
    if (first) return first.slice(0, 64);
  }
  const real = request.headers.get("x-real-ip")?.trim();
  if (real) return real.slice(0, 64);
  return "unknown";
}

export function takeExtractSlot(ip: string): { ok: true } | { ok: false; retryAfterSec: number } {
  const now = Date.now();
  globalHits = prune(globalHits, now);
  const bucket = byIp.get(ip) ?? { hits: [], inFlight: 0 };
  bucket.hits = prune(bucket.hits, now);

  if (bucket.inFlight >= CONCURRENT_IP || globalInFlight >= CONCURRENT_GLOBAL) {
    return { ok: false, retryAfterSec: 15 };
  }
  if (bucket.hits.length >= PER_IP) {
    return { ok: false, retryAfterSec: retryAfterSec(bucket.hits, PER_IP, now) };
  }
  if (globalHits.length >= GLOBAL) {
    return { ok: false, retryAfterSec: retryAfterSec(globalHits, GLOBAL, now) };
  }

  bucket.hits.push(now);
  bucket.inFlight += 1;
  byIp.set(ip, bucket);
  globalHits.push(now);
  globalInFlight += 1;
  return { ok: true };
}

export function releaseExtractSlot(ip: string): void {
  const bucket = byIp.get(ip);
  if (bucket && bucket.inFlight > 0) bucket.inFlight -= 1;
  if (globalInFlight > 0) globalInFlight -= 1;
}
