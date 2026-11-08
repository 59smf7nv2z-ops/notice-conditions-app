import { inflateRawSync } from "node:zlib";
import iconv from "iconv-lite";
import JSZip from "jszip";
import * as CFB from "cfb";
import { IMAGE_TYPES, MAX_INFLATE_BYTES, MAX_ZIP_UNCOMPRESSED, MIN_TEXT } from "./schema";

export type ContentBlock =
  | { type: "text"; text: string }
  | { type: "image"; source: { type: "base64"; media_type: string; data: string } }
  | { type: "document"; source: { type: "base64"; media_type: string; data: string } };

export type UploadedFile = { name: string; bytes: Buffer };

function extOf(name: string): string {
  const i = name.lastIndexOf(".");
  return i >= 0 ? name.slice(i).toLowerCase() : "";
}

function zipUncompressedBytes(z: JSZip): number {
  let total = 0;
  z.forEach((_, file) => {
    if (file.dir) return;
    const size = (file as { _data?: { uncompressedSize?: number } })._data?.uncompressedSize;
    total += typeof size === "number" && Number.isFinite(size) ? size : 0;
  });
  return total;
}

function assertZipBudget(z: JSZip): void {
  if (zipUncompressedBytes(z) > MAX_ZIP_UNCOMPRESSED) {
    throw new Error("압축을 풀면 용량이 너무 큽니다");
  }
}

function readHwpx(bytes: Buffer): Promise<string> {
  return JSZip.loadAsync(bytes).then(async (z) => {
    assertZipBudget(z);
    const names = Object.keys(z.files)
      .filter((n) => /^Contents\/section\d+\.xml$/.test(n))
      .sort();
    const lines: string[] = [];
    for (const name of names) {
      const xml = await z.files[name].async("string");
      for (const para of xml.match(/<hp:p\b.*?<\/hp:p>/gs) ?? []) {
        const text = (para.match(/<hp:t>(.*?)<\/hp:t>/gs) ?? [])
          .map((t) => t.replace(/<hp:t>|<\/hp:t>/g, ""))
          .join("");
        const cleaned = text.replace(/<[^>]+>/g, "").trim();
        if (cleaned) lines.push(cleaned);
      }
    }
    return lines.join("\n");
  });
}

const CHAR_CTRL = new Set([0, 10, 13, 24, 25, 26, 27, 28, 29, 30, 31]);
const LONG_CTRL = new Set([1, 2, 3, 4, 5, 6, 7, 8, 9, 11, 12, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23]);

function hwpClean(raw: Buffer): string {
  const out: string[] = [];
  let i = 0;
  const n = Math.floor(raw.length / 2);
  while (i < n) {
    const code = raw.readUInt16LE(i * 2);
    if (LONG_CTRL.has(code)) {
      if (code === 9) out.push(" ");
      i += 8;
    } else if (CHAR_CTRL.has(code)) {
      if (code === 10 || code === 13) out.push("\n");
      i += 1;
    } else {
      out.push(String.fromCharCode(code));
      i += 1;
    }
  }
  return out.join("");
}

function cfbContent(entry: CFB.CFB$Entry | null | undefined): Buffer {
  if (!entry || entry.content == null) return Buffer.alloc(0);
  const c = entry.content as Buffer | number[] | Uint8Array;
  return Buffer.from(c);
}

function readHwp(bytes: Buffer): string {
  const cfb = CFB.read(bytes, { type: "buffer" });
  const header = cfbContent(CFB.find(cfb, "FileHeader"));
  if (header.subarray(0, 17).toString("latin1") !== "HWP Document File") {
    throw new Error("HWP 문서가 아닙니다");
  }
  if (header.length > 36 && header[36] & 2) {
    throw new Error("암호가 걸린 문서입니다");
  }
  const compressed = header.length > 36 ? Boolean(header[36] & 1) : false;
  const sections = cfb.FullPaths.map((p, i) => ({ path: p.replace(/\\/g, "/"), entry: cfb.FileIndex[i] }))
    .filter(({ path, entry }) => entry && /(^|\/)BodyText\/Section\d+$/i.test(path))
    .sort((a, b) => Number(a.entry.name.replace(/\D/g, "")) - Number(b.entry.name.replace(/\D/g, "")))
    .map((x) => x.entry);
  const paras: string[] = [];
  for (const sec of sections.slice(0, 24)) {
    let data = cfbContent(sec);
    if (!data.length) continue;
    if (compressed) {
      if (data.length > MAX_INFLATE_BYTES) {
        throw new Error("압축된 본문이 너무 큽니다");
      }
      data = inflateRawSync(data, { maxOutputLength: MAX_INFLATE_BYTES });
    }
    if (data.length > MAX_INFLATE_BYTES) {
      throw new Error("풀어 낸 본문이 너무 큽니다");
    }
    let i = 0;
    while (i + 4 <= data.length) {
      const h = data.readUInt32LE(i);
      const tag = h & 0x3ff;
      let size = (h >> 20) & 0xfff;
      i += 4;
      if (size === 0xfff) {
        if (i + 4 > data.length) break;
        size = data.readUInt32LE(i);
        i += 4;
      }
      if (tag === 67 && i + size <= data.length) {
        paras.push(hwpClean(data.subarray(i, i + size)));
      }
      i += size;
    }
  }
  return paras.filter((p) => p.trim()).join("\n");
}

async function readDocx(bytes: Buffer): Promise<string> {
  const z = await JSZip.loadAsync(bytes);
  assertZipBudget(z);
  const file = z.file("word/document.xml");
  if (!file) throw new Error("docx 본문을 찾지 못했습니다");
  const xml = await file.async("string");
  const lines: string[] = [];
  for (const para of xml.match(/<w:p\b.*?<\/w:p>/gs) ?? []) {
    const text = (para.match(/<w:t[^>]*>(.*?)<\/w:t>/gs) ?? [])
      .map((t) => t.replace(/<w:t[^>]*>|<\/w:t>/g, ""))
      .join("")
      .trim();
    if (text) lines.push(text);
  }
  return lines.join("\n");
}

function readTextAny(bytes: Buffer): string {
  if (bytes.length >= 3 && bytes[0] === 0xef && bytes[1] === 0xbb && bytes[2] === 0xbf) {
    return bytes.subarray(3).toString("utf8");
  }
  try {
    return new TextDecoder("utf-8", { fatal: true }).decode(bytes);
  } catch {
    try {
      return iconv.decode(bytes, "cp949");
    } catch {
      return bytes.toString("utf8");
    }
  }
}

function readHtml(bytes: Buffer): string {
  let raw = readTextAny(bytes);
  raw = raw.replace(/<(script|style)[\s\S]*?<\/\1>/gi, " ");
  raw = raw.replace(/<br\s*\/?>|<\/p>|<\/tr>|<\/li>|<\/div>/gi, "\n");
  const text = raw
    .replace(/<[^>]+>/g, " ")
    .replace(/&nbsp;/g, " ")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&amp;/g, "&")
    .replace(/&quot;/g, '"');
  return text
    .split(/\n/)
    .map((l) => l.trim())
    .filter(Boolean)
    .join("\n");
}

async function readByExt(ext: string, bytes: Buffer): Promise<string> {
  if (ext === ".hwpx") return readHwpx(bytes);
  if (ext === ".hwp") return readHwp(bytes);
  if (ext === ".docx") return readDocx(bytes);
  if (ext === ".html" || ext === ".htm") return readHtml(bytes);
  if (ext === ".txt" || ext === ".md" || ext === ".csv") return readTextAny(bytes);
  throw new Error("unsupported");
}

const TEXT_EXTS = new Set([".hwpx", ".hwp", ".docx", ".html", ".htm", ".txt", ".md", ".csv"]);

export async function fileToBlocks(file: UploadedFile): Promise<{ blocks: ContentBlock[] | null; why: string | null }> {
  const ext = extOf(file.name);
  const name = file.name.replace(/[/\\]/g, "_");
  if (TEXT_EXTS.has(ext)) {
    try {
      const text = await readByExt(ext, file.bytes);
      if (text.trim().length < MIN_TEXT) {
        return {
          blocks: null,
          why: `읽어 낸 글자가 ${text.trim().length}자뿐입니다(도형·그림 위주 문서일 수 있음). PDF 나 이미지로 저장해서 넣어 주세요`,
        };
      }
      return { blocks: [{ type: "text", text: `[파일: ${name}]\n${text}` }], why: null };
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      return { blocks: null, why: `읽기 실패(${msg}). PDF 나 이미지로 저장해서 넣어 주세요` };
    }
  }
  if (ext in IMAGE_TYPES) {
    return {
      blocks: [
        { type: "text", text: `[이미지 파일: ${name}]` },
        {
          type: "image",
          source: { type: "base64", media_type: IMAGE_TYPES[ext], data: file.bytes.toString("base64") },
        },
      ],
      why: null,
    };
  }
  if (ext === ".pdf") {
    return {
      blocks: [
        { type: "text", text: `[PDF 파일: ${name}]` },
        {
          type: "document",
          source: { type: "base64", media_type: "application/pdf", data: file.bytes.toString("base64") },
        },
      ],
      why: null,
    };
  }
  return {
    blocks: null,
    why: `지원하지 않는 형식(${ext || "확장자 없음"}). PDF 나 이미지로 저장해서 넣어 주세요`,
  };
}
