import type { ExtractKind } from "@/lib/types";

export function KindBadge({ kind, count, large }: { kind: ExtractKind; count?: number; large?: boolean }) {
  const bundle = kind === "묶음";
  const text = bundle ? `묶음 추출 · ${count ?? 0}건` : "단건 추출";
  const cls = bundle
    ? "bg-teal-100 text-teal-950 ring-teal-300"
    : "bg-slate-100 text-slate-800 ring-slate-300";
  return (
    <span
      className={`inline-flex items-center rounded-full font-semibold ring-1 ${cls} ${
        large ? "px-3 py-1 text-sm" : "px-2 py-0.5 text-[11px]"
      }`}
    >
      {text}
    </span>
  );
}
