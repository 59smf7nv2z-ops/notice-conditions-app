import { getIdentity } from "../../../cursor/identity";
import { extractNotice } from "../../../lib/extract";
import {
  json,
  MAX_FILE_BYTES,
  MAX_FILES,
  MAX_TOTAL_BYTES,
  sameOrigin,
  sanitizeName,
} from "../../../lib/http";
import { extractCsrfOk } from "../../../lib/csrf";
import { clientIp, releaseExtractSlot, takeExtractSlot } from "../../../lib/rate-limit";
import type { UploadedFile } from "../../../lib/readers";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
export const maxDuration = 120;

export async function POST(request: Request) {
  const identity = await getIdentity(request);
  if (identity.verified && identity.kind === "key" && identity.appVisibility === "public") {
    return json({ error: "이 API는 공개 호출을 받지 않습니다." }, 403);
  }
  if (!sameOrigin(request)) {
    return json({ error: "잘못된 요청 출처입니다." }, 403);
  }
  if (!extractCsrfOk(request)) {
    return json({ error: "세션이 만료되었거나 잘못된 요청입니다. 페이지를 새로고침해 주세요." }, 403);
  }

  const ip = clientIp(request);
  const slot = takeExtractSlot(ip);
  if (!slot.ok) {
    return json({ error: "요청이 너무 많습니다. 잠시 후 다시 시도해 주세요." }, 429, {
      "retry-after": String(slot.retryAfterSec),
    });
  }

  try {
    return await runExtract(request);
  } finally {
    releaseExtractSlot(ip);
  }
}

async function runExtract(request: Request): Promise<Response> {
  let form: FormData;
  try {
    form = await request.formData();
  } catch {
    return json({ error: "업로드를 읽지 못했습니다." }, 400);
  }

  const name = sanitizeName(String(form.get("name") ?? ""));
  const parts = form.getAll("files");
  if (parts.length === 0) {
    return json({ error: "파일을 한 개 이상 올려 주세요." }, 400);
  }
  if (parts.length > MAX_FILES) {
    return json({ error: `한 공고에 파일은 ${MAX_FILES}개까지입니다.` }, 413);
  }

  const files: UploadedFile[] = [];
  let total = 0;
  for (const part of parts) {
    if (typeof part === "string") {
      return json({ error: "파일 형식이 아닙니다." }, 400);
    }
    const file = part as File;
    const rawName = (file.name || "파일").replace(/[/\\]/g, "_").slice(0, 200);
    if (file.size > MAX_FILE_BYTES) {
      return json({ error: `${rawName} 파일이 너무 큽니다(파일당 최대 12MB).` }, 413);
    }
    total += file.size;
    if (total > MAX_TOTAL_BYTES) {
      return json({ error: "한 공고의 전체 용량은 24MB를 넘을 수 없습니다." }, 413);
    }
    const buf = Buffer.from(await file.arrayBuffer());
    files.push({ name: rawName, bytes: buf });
  }

  try {
    const result = await extractNotice(name, files);
    if (!Object.keys(result.결과).length && result.skipped.length && !result.readText) {
      return json({ error: "읽을 수 있는 파일이 없습니다.", ...result }, 400);
    }
    return json(result);
  } catch (e) {
    const message = e instanceof Error ? e.message : "추출에 실패했습니다.";
    const safe = /api[_-]?key|sk-ant/i.test(message) ? "추출 서비스 오류가 났습니다." : message;
    return json({ error: safe }, 502);
  }
}
