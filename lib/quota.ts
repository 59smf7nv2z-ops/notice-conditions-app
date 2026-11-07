import type { Identity } from "../cursor/identity";

/** Live Anthropic extract is only for a verified person (or a non-public API key). Anonymous visitors never spend quota. */
export function canSpendExtractQuota(identity: Identity): boolean {
  if (!identity.verified) return false;
  if (identity.kind === "key" && identity.appVisibility === "public") return false;
  return true;
}

export const QUOTA_GATE_MESSAGE =
  "로그인한 담당자만 실제 조건 추출을 쓸 수 있습니다. Cursor에 로그인한 뒤 다시 시도해 주세요.";
