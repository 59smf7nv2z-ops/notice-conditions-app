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

function headerHost(request: Request, name: string): string {
  const raw = request.headers.get(name);
  if (!raw) return "";
  return canonHost(raw.split(",")[0].trim());
}

function forwardedRfcHost(request: Request): string {
  const raw = request.headers.get("forwarded");
  if (!raw) return "";
  const match = raw.match(/(?:^|[;,])\s*host="?([^;,"\s]+)"?/i);
  return match ? canonHost(match[1]) : "";
}

function envHosts(): string[] {
  const raw = [
    process.env["VERCEL_PROJECT_PRODUCTION_URL"],
    process.env["VERCEL_URL"],
  ];
  const hosts: string[] = [];
  for (const value of raw) {
    const trimmed = value?.trim();
    if (!trimmed) continue;
    const host = hostOf(trimmed.includes("://") ? trimmed : `https://${trimmed}`);
    if (host) hosts.push(host);
  }
  return hosts;
}

function trustedHosts(request: Request): Set<string> {
  return new Set(
    [
      headerHost(request, "host"),
      headerHost(request, "x-forwarded-host"),
      forwardedRfcHost(request),
      canonHost(new URL(request.url).host),
      ...envHosts(),
      // Cursor Apps public URL is not always Host/request.url on the function.
      "notice-conditions.apps.grok.bot",
    ].filter(Boolean),
  );
}

/** POST extract: Origin must match this app. Missing Origin fails. */
export function sameOrigin(request: Request): boolean {
  const origin = request.headers.get("origin");
  if (!origin) return false;
  const originHost = hostOf(origin);
  if (!originHost) return false;
  return trustedHosts(request).has(originHost);
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
