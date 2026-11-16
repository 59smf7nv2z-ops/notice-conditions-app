import { createHmac, randomBytes, timingSafeEqual } from "node:crypto";

export const CSRF_COOKIE = "nc_extract";
export const CSRF_HEADER = "x-extract-csrf";
const MAX_AGE_SEC = 2 * 60 * 60;

function secret(): string {
  const appId = (process.env["CURSOR_APP_ID"] ?? "").trim();
  if (appId) return appId;
  const key = (process.env["ANTHROPIC_API_KEY"] ?? "").trim();
  if (key) return key;
  return "notice-conditions-dev-csrf";
}

function mac(body: string): string {
  return createHmac("sha256", secret()).update(body).digest("hex");
}

function equal(a: string, b: string): boolean {
  const left = Buffer.from(a);
  const right = Buffer.from(b);
  if (left.length !== right.length) return false;
  return timingSafeEqual(left, right);
}

export function mintCsrf(): string {
  const ts = Math.floor(Date.now() / 1000).toString();
  const nonce = randomBytes(16).toString("hex");
  const body = `v1.${ts}.${nonce}`;
  return `${body}.${mac(body)}`;
}

export function verifyCsrf(token: string): boolean {
  const parts = token.split(".");
  if (parts.length !== 4 || parts[0] !== "v1") return false;
  const body = `${parts[0]}.${parts[1]}.${parts[2]}`;
  if (!equal(mac(body), parts[3])) return false;
  const issued = Number(parts[1]);
  if (!Number.isFinite(issued)) return false;
  const now = Math.floor(Date.now() / 1000);
  return now + 30 >= issued && now - issued < MAX_AGE_SEC;
}

export function readCsrfCookie(request: Request): string {
  const raw = request.headers.get("cookie") ?? "";
  for (const part of raw.split(";")) {
    const [name, ...rest] = part.trim().split("=");
    if (name === CSRF_COOKIE) return decodeURIComponent(rest.join("="));
  }
  return "";
}

export function csrfCookieHeader(token: string, request: Request): string {
  const https = new URL(request.url).protocol === "https:";
  const parts = [
    `${CSRF_COOKIE}=${encodeURIComponent(token)}`,
    "Path=/",
    "HttpOnly",
    "SameSite=Strict",
    `Max-Age=${MAX_AGE_SEC}`,
  ];
  if (https) parts.push("Secure");
  return parts.join("; ");
}

/** Cookie + header must match a live signed token. Browsers send the cookie; scripts cannot read HttpOnly. */
export function extractCsrfOk(request: Request): boolean {
  const header = (request.headers.get(CSRF_HEADER) ?? "").trim();
  const cookie = readCsrfCookie(request);
  if (!header || !cookie) return false;
  if (!equal(header, cookie)) return false;
  return verifyCsrf(header);
}
