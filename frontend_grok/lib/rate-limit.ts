import { randomUUID } from "node:crypto";
import { sql } from "./db";

const WINDOW_MS = 10 * 60 * 1000;
const PER_IP = 8;
const GLOBAL = 40;
const CONCURRENT_IP = 2;
const CONCURRENT_GLOBAL = 6;
const LEASE_MS = 3 * 60 * 1000;

type MemoryBucket = { hits: number[]; inFlight: number };
const byIp = new Map<string, MemoryBucket>();
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

function takeMemory(ip: string): { ok: true; leaseId: string } | { ok: false; retryAfterSec: number } {
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
  return { ok: true, leaseId: `mem:${ip}` };
}

function releaseMemory(ip: string): void {
  const bucket = byIp.get(ip);
  if (bucket && bucket.inFlight > 0) bucket.inFlight -= 1;
  if (globalInFlight > 0) globalInFlight -= 1;
}

async function takeShared(ip: string): Promise<{ ok: true; leaseId: string } | { ok: false; retryAfterSec: number }> {
  await sql(`delete from extract_inflight where expires_at < now()`);
  await sql(`delete from extract_hits where created_at < now() - interval '10 minutes'`);

  const inflight = await sql<{ ip_n: string; all_n: string }>(
    `select
       (select count(*)::text from extract_inflight where ip = $1) as ip_n,
       (select count(*)::text from extract_inflight) as all_n`,
    [ip],
  );
  const ipIn = Number(inflight[0]?.ip_n ?? 0);
  const allIn = Number(inflight[0]?.all_n ?? 0);
  if (ipIn >= CONCURRENT_IP || allIn >= CONCURRENT_GLOBAL) {
    return { ok: false, retryAfterSec: 15 };
  }

  const counts = await sql<{ ip_n: string; all_n: string }>(
    `select
       (select count(*)::text from extract_hits where ip = $1) as ip_n,
       (select count(*)::text from extract_hits) as all_n`,
    [ip],
  );
  const ipHits = Number(counts[0]?.ip_n ?? 0);
  const allHits = Number(counts[0]?.all_n ?? 0);
  if (ipHits >= PER_IP || allHits >= GLOBAL) {
    const oldest = await sql<{ created_at: Date }>(
      ipHits >= PER_IP
        ? `select created_at from extract_hits where ip = $1 order by created_at asc limit 1 offset $2`
        : `select created_at from extract_hits order by created_at asc limit 1 offset $2`,
      ipHits >= PER_IP ? [ip, Math.max(0, PER_IP - 1)] : ["", Math.max(0, GLOBAL - 1)],
    );
    const t = oldest[0]?.created_at ? new Date(oldest[0].created_at).getTime() : Date.now();
    return { ok: false, retryAfterSec: Math.max(1, Math.ceil((WINDOW_MS - (Date.now() - t)) / 1000)) };
  }

  const leaseId = randomUUID();
  await sql(`insert into extract_hits (ip) values ($1)`, [ip]);
  await sql(`insert into extract_inflight (id, ip, expires_at) values ($1, $2, now() + interval '3 minutes')`, [
    leaseId,
    ip,
  ]);
  return { ok: true, leaseId };
}

export async function takeExtractSlot(
  ip: string,
): Promise<{ ok: true; leaseId: string } | { ok: false; retryAfterSec: number }> {
  try {
    return await takeShared(ip);
  } catch {
    return takeMemory(ip);
  }
}

export async function releaseExtractSlot(leaseId: string, ip: string): Promise<void> {
  if (leaseId.startsWith("mem:")) {
    releaseMemory(ip);
    return;
  }
  try {
    await sql(`delete from extract_inflight where id = $1`, [leaseId]);
  } catch {
    releaseMemory(ip);
  }
}
