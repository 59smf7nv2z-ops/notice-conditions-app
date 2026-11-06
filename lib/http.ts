import { MAX_FILE_BYTES, MAX_FILES, MAX_TOTAL_BYTES } from "./schema";

const NO_STORE = { "cache-control": "private, no-store" };

export function json(data: unknown, status = 200, extraHeaders?: Record<string, string>): Response {
  return Response.json(data, { status, headers: { ...NO_STORE, ...extraHeaders } });
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

function requestHost(request: Request): string {
  return canonHost(new URL(request.url).host);
}

/** POST extract: Origin must match the request host. Sec-Fetch-Site is never an allow. */
export function sameOrigin(request: Request): boolean {
  const origin = request.headers.get("origin");
  if (!origin) return false;
  const originHost = hostOf(origin);
  if (!originHost) return false;
  if (originHost !== requestHost(request)) return false;

  const site = (request.headers.get("sec-fetch-site") || "").toLowerCase();
  if (site === "cross-site" || site === "none") return false;
  return true;
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
