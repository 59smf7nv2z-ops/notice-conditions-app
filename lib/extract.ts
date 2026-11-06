import Anthropic from "@anthropic-ai/sdk";
import type { ContentBlock, UploadedFile } from "./readers";
import { fileToBlocks } from "./readers";
import { KEYMAP, MODEL, MAX_TOKENS, SUBMIT_HINT, SYSTEM_PROMPT, TOOL } from "./schema";
import { normalize, shapeProblems, toKoreanResult, type FieldValue, type RawResult } from "./normalize";
import { mockRecord } from "./mock";

export type ExtractOk = {
  공고: string;
  모델: string;
  결과: Record<string, FieldValue>;
  skipped: string[];
  readText: string;
  mock: boolean;
  warnings: string[];
};

function blocksToSdk(blocks: ContentBlock[]): Anthropic.ContentBlockParam[] {
  return blocks.map((b) => {
    if (b.type === "text") return { type: "text" as const, text: b.text };
    if (b.type === "image") {
      return {
        type: "image" as const,
        source: { type: "base64" as const, media_type: b.source.media_type as "image/png" | "image/jpeg" | "image/gif" | "image/webp", data: b.source.data },
      };
    }
    return {
      type: "document" as const,
      source: { type: "base64" as const, media_type: "application/pdf" as const, data: b.source.data },
    };
  });
}

export async function gatherBlocks(files: UploadedFile[]) {
  const blocks: ContentBlock[] = [];
  const skipped: string[] = [];
  for (const f of files) {
    const { blocks: b, why } = await fileToBlocks(f);
    if (b == null) skipped.push(`${f.name} - ${why}`);
    else blocks.push(...b);
  }
  const readText = blocks.filter((b): b is { type: "text"; text: string } => b.type === "text").map((b) => b.text).join("\n\n");
  return { blocks, skipped, readText };
}

export async function extractNotice(name: string, files: UploadedFile[]): Promise<ExtractOk> {
  const { blocks, skipped, readText } = await gatherBlocks(files);
  if (!blocks.length) {
    return {
      공고: name,
      모델: MODEL,
      결과: {},
      skipped,
      readText: "",
      mock: false,
      warnings: ["읽을 수 있는 파일이 없거나 결과가 비었습니다."],
    };
  }

  const apiKey = process.env.ANTHROPIC_API_KEY;
  if (!apiKey) {
    const raw = mockRecord(readText, name);
    const { fixed, warnings } = normalize(raw);
    return {
      공고: name,
      모델: `${MODEL} (샘플)`,
      결과: toKoreanResult(fixed),
      skipped,
      readText,
      mock: true,
      warnings: ["ANTHROPIC_API_KEY 가 없어 샘플 결과로 채웠습니다. 실제 추출은 비밀 값을 넣은 뒤 다시 실행하세요.", ...warnings],
    };
  }

  const client = new Anthropic({ apiKey });
  const userBlocks = [...blocksToSdk(blocks), { type: "text" as const, text: SUBMIT_HINT }];
  let messages: Anthropic.MessageParam[] = [{ role: "user", content: userBlocks }];
  let last: RawResult | null = null;

  for (let attempt = 0; attempt < 2; attempt++) {
    const resp = await client.messages.create({
      model: MODEL,
      max_tokens: MAX_TOKENS,
      system: SYSTEM_PROMPT,
      tools: [TOOL as Anthropic.Tool],
      messages,
    });
    const call = resp.content.find((b) => b.type === "tool_use");
    if (!call || call.type !== "tool_use") {
      messages = [
        ...messages,
        { role: "assistant", content: resp.content },
        { role: "user", content: "글로 답하지 말고 record_notice 도구를 호출해서 제출하라." },
      ];
      continue;
    }
    last = call.input as RawResult;
    const problems = shapeProblems(last);
    if (!problems.length) {
      const { fixed, warnings } = normalize(last);
      return {
        공고: name,
        모델: MODEL,
        결과: toKoreanResult({ ...Object.fromEntries(Object.keys(KEYMAP).map((k) => [k, fixed[k] ?? { value: null, evidence: null }])), ...fixed }),
        skipped,
        readText,
        mock: false,
        warnings,
      };
    }
    messages = [
      ...messages,
      { role: "assistant", content: resp.content },
      {
        role: "user",
        content: [
          {
            type: "tool_result",
            tool_use_id: call.id,
            is_error: true,
            content:
              "모양이 맞지 않는다: " +
              problems.join("; ") +
              ". 모든 항목을 빠짐없이 {value, evidence} 모양으로 다시 제출하라.",
          },
        ],
      },
    ];
  }

  if (!last) {
    return {
      공고: name,
      모델: MODEL,
      결과: {},
      skipped,
      readText,
      mock: false,
      warnings: ["도구 호출이 없어 결과를 받지 못했습니다."],
    };
  }
  const { fixed, warnings } = normalize(last);
  return {
    공고: name,
    모델: MODEL,
    결과: toKoreanResult(fixed),
    skipped,
    readText,
    mock: false,
    warnings,
  };
}
