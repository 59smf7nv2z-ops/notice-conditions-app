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

function isInternalHost(host: string): boolean {
  return host === "loopback" || host === "0.0.0.0" || !host.includes(".");
}

function headerHost(request: Request, name: string): string {
  const raw = request.headers.get(name);
  if (!raw) return "";
  return canonHost(raw.split(",")[0].trim());
}

/** Public Host / X-Forwarded-Host first. request.url is often an internal listener. */
function publicHost(request: Request): string {
  const header = headerHost(request, "host");
  const forwarded = headerHost(request, "x-forwarded-host");
  const urlHost = canonHost(new URL(request.url).host);
  if (header && !isInternalHost(header)) return header;
  if (forwarded && !isInternalHost(forwarded)) return forwarded;
  if (urlHost && !isInternalHost(urlHost)) return urlHost;
  return header || forwarded || urlHost;
}

/** POST extract: Origin must match the public site host. Missing Origin fails. */
export function sameOrigin(request: Request): boolean {
  const origin = request.headers.get("origin");
  if (!origin) return false;
  const originHost = hostOf(origin);
  if (!originHost) return false;
  if (originHost !== publicHost(request)) return false;

  const site = (request.headers.get("sec-fetch-site") || "").toLowerCase();
  if (site === "cross-site") return false;
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
