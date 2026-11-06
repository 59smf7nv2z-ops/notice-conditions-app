import { MAX_FILE_BYTES, MAX_FILES, MAX_TOTAL_BYTES } from "./schema";

const NO_STORE = { "cache-control": "private, no-store" };

export function json(data: unknown, status = 200): Response {
  return Response.json(data, { status, headers: NO_STORE });
}

export function sameOrigin(request: Request): boolean {
  const origin = request.headers.get("origin");
  if (!origin) {
    const referer = request.headers.get("referer");
    if (!referer) return true;
    try {
      return new URL(referer).origin === new URL(request.url).origin;
    } catch {
      return false;
    }
  }
  return origin === new URL(request.url).origin;
}

export function sanitizeName(raw: string): string {
  const cleaned = raw.replace(/[/\\?%*:|"<>]/g, "_").replace(/\s+/g, " ").trim();
  return cleaned.slice(0, 80) || "공고";
}

export { MAX_FILE_BYTES, MAX_FILES, MAX_TOTAL_BYTES };
