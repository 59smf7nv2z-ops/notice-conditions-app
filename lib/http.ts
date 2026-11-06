import { MAX_FILE_BYTES, MAX_FILES, MAX_TOTAL_BYTES } from "./schema";

const NO_STORE = { "cache-control": "private, no-store" };

export function json(data: unknown, status = 200): Response {
  return Response.json(data, { status, headers: NO_STORE });
}

function canonHost(host: string): string {
  const h = host.split(":")[0].toLowerCase();
  if (h === "localhost" || h === "127.0.0.1" || h === "[::1]" || h === "::1") return "loopback";
  return h;
}

function hostOf(urlLike: string): string | null {
  try {
    return canonHost(new URL(urlLike).host);
  } catch {
    return null;
  }
}

export function sameOrigin(request: Request): boolean {
  const site = (request.headers.get("sec-fetch-site") || "").toLowerCase();
  if (site === "same-origin" || site === "none") return true;

  const forwarded = request.headers.get("x-forwarded-host");
  const hostHdr = request.headers.get("host");
  const reqHost = canonHost(forwarded || hostHdr || new URL(request.url).host);

  const origin = request.headers.get("origin");
  if (origin) {
    const originHost = hostOf(origin);
    return Boolean(originHost && originHost === reqHost);
  }
  const referer = request.headers.get("referer");
  if (!referer) return true;
  const refHost = hostOf(referer);
  return Boolean(refHost && refHost === reqHost);
}

/** Bracket env read so Next.js cannot inline an empty key at build time. */
export function anthropicApiKey(): string {
  return (process.env["ANTHROPIC_API_KEY"] ?? "").trim();
}

export function sanitizeName(raw: string): string {
  const cleaned = raw.replace(/[/\\?%*:|"<>]/g, "_").replace(/\s+/g, " ").trim();
  return cleaned.slice(0, 80) || "공고";
}

export { MAX_FILE_BYTES, MAX_FILES, MAX_TOTAL_BYTES };
