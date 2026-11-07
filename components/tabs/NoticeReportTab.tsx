"use client";

import { useMemo, useState } from "react";
import { useDashboard } from "@/components/DashboardProvider";
import { csvEscape, downloadBlob, flat } from "@/lib/download";
import { PRIVACY_NOTICE, benefitLine, buildGuideByTone, candidatesOf } from "@/lib/guide";
import { SAMPLE_BUILDINGS, withAge } from "@/lib/registry";
import sampleExtract from "@/lib/sample-extract.json";
import { judgeBuilding } from "@/lib/compare";
import type { BuildingRecord, Extracted, GuideTone, Verdict } from "@/lib/types";

const TONES: { id: GuideTone; label: string }[] = [
  { id: "elder", label: "어르신 맞춤형" },
  { id: "official", label: "공식 행정문서형" },
  { id: "sms", label: "알림톡/SMS 문자형" },
];

function mockBuilding(notice: Extracted): BuildingRecord {
  const fill = withAge(SAMPLE_BUILDINGS.해당);
  const judged = judgeBuilding(notice, fill);
  return {
    id: "sample",
    ...fill,
    noticeName: notice.공고,
    ...judged,
  };
}

function Badge({ v }: { v: Verdict }) {
  const text = v === "해당" ? "해당(적합)" : v === "비해당" ? "비해당(불적합)" : "확인필요(수동검토)";
  const cls =
    v === "해당"
      ? "bg-emerald-100 text-emerald-900 ring-emerald-300"
      : v === "비해당"
        ? "bg-rose-100 text-rose-900 ring-rose-300"
        : "bg-orange-100 text-orange-950 ring-orange-300";
  return (
    <span className={`inline-flex rounded-full px-3 py-1 text-sm font-bold ring-1 ${cls}`}>{text}</span>
  );
}

export function NoticeReportTab() {
  const { notice, notices, buildings, liveMatch, resetForNextMatch } = useDashboard();
  const [tone, setTone] = useState<GuideTone>("elder");
  const [variant, setVariant] = useState(0);
  const [edited, setEdited] = useState<string | null>(null);

  const activeNotice = notice ?? (sampleExtract as Extracted);
  const summary = liveMatch ?? buildings[0] ?? mockBuilding(activeNotice);
  const usingMock = !liveMatch && !buildings[0];
  const support = flat(activeNotice.결과["지원내용"]?.value) || "무료 안전점검";
  const benefit = benefitLine(summary.overall, support);

  const generated = useMemo(
    () => buildGuideByTone(tone, activeNotice, summary, variant),
    [tone, activeNotice, summary, variant],
  );
  const text = edited ?? generated;

  const candidates = useMemo(() => {
    const list = candidatesOf(buildings);
    if (liveMatch && (liveMatch.overall === "해당" || liveMatch.overall === "확인필요")) {
      if (!list.some((b) => b.address === liveMatch.address)) return [liveMatch, ...list];
    }
    if (!list.length && (summary.overall === "해당" || summary.overall === "확인필요")) return [summary];
    return list;
  }, [buildings, liveMatch, summary]);

  const reportCsv = useMemo(() => {
    const cols = ["주소", "용도", "사용승인일", "경과연수", "1차판정", "공고"];
    const lines = [cols.map(csvEscape).join(",")];
    const rows = candidates.length ? candidates : [summary];
    for (const b of rows) {
      lines.push(
        [b.address, b.use, b.approvalDate || "", b.ageYears, b.overall, b.noticeName].map(csvEscape).join(","),
      );
    }
    return "\uFEFF" + lines.join("\n");
  }, [candidates, summary]);

  function pickTone(next: GuideTone) {
    setTone(next);
    setEdited(null);
  }

  function regenerate() {
    setVariant((v) => v + 1);
    setEdited(null);
  }

  return (
    <div className="space-y-6">
      <section className="print:hidden">
        <h2 className="text-lg font-semibold text-gov-900">맞춤형 안내문 및 결과 리포트</h2>
        <p className="mt-1 text-sm text-slate-600">
          앞 단계에서 본 건물 요약과 1차 판정으로 안내문 초안을 만듭니다. 말투를 고르면 문구가 바로 바뀝니다.
        </p>
      </section>

      <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <p className="text-xs font-semibold tracking-wide text-slate-500">1차 검토 요약</p>
            <p className="mt-1 text-lg font-semibold text-gov-900">{summary.address || "주소 미입력"}</p>
            <p className="mt-1 text-sm text-slate-600">
              용도 {summary.use || "—"} · 사용승인일 {summary.approvalDate || "—"} · 경과 {summary.ageYears || "—"}년
            </p>
            <p className="mt-2 text-sm font-medium text-accent-ink">{benefit}</p>
            {usingMock ? (
              <p className="mt-1 text-xs text-slate-500">대조 전이면 샘플 건물 요약입니다. 2번 탭에서 대상을 고르면 바뀝니다.</p>
            ) : null}
          </div>
          <Badge v={summary.overall} />
        </div>
      </section>

      <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm print:border-0 print:shadow-none">
        <p className="text-sm font-medium print:hidden">안내문 말투</p>
        <div className="mt-2 flex flex-wrap gap-2 print:hidden">
          {TONES.map((t) => (
            <button
              key={t.id}
              type="button"
              className={`rounded-lg px-3 py-2 text-sm font-semibold ring-1 ${
                tone === t.id
                  ? "bg-gov-700 text-white ring-gov-700"
                  : "bg-white text-slate-800 ring-slate-200 hover:bg-slate-50"
              }`}
              onClick={() => pickTone(t.id)}
            >
              {t.label}
              {t.id === "elder" ? " (기본)" : ""}
            </button>
          ))}
          <button
            type="button"
            className="rounded-lg bg-slate-100 px-3 py-2 text-sm font-medium text-slate-800 hover:bg-slate-200"
            onClick={regenerate}
          >
            문구 재생성
          </button>
        </div>
        <label className="mt-4 block text-sm font-medium" htmlFor="guide-body">
          안내문 초안
        </label>
        <textarea
          id="guide-body"
          className="mt-1 min-h-[18rem] w-full rounded-xl border border-slate-200 bg-white p-4 text-sm leading-relaxed shadow-inner outline-none ring-gov-600 focus:ring-2 print:min-h-0 print:border-0 print:shadow-none"
          value={text}
          onChange={(e) => setEdited(e.target.value)}
        />
      </section>

      <section className="flex flex-wrap gap-2 print:hidden">
        <button
          type="button"
          className="rounded-lg bg-gov-700 px-4 py-2 text-sm font-semibold text-white hover:bg-gov-800"
          onClick={() => downloadBlob("1차후보자목록.csv", new Blob([reportCsv], { type: "text/csv;charset=utf-8" }))}
        >
          1차 후보자 목록 CSV
        </button>
        <button
          type="button"
          className="rounded-lg bg-slate-100 px-4 py-2 text-sm font-semibold text-slate-800 hover:bg-slate-200"
          onClick={() => window.print()}
        >
          안내문 인쇄/PDF 저장
        </button>
        <button
          type="button"
          className="rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm font-semibold text-slate-800 hover:bg-slate-50"
          onClick={resetForNextMatch}
        >
          다음 대조 진행(초기화)
        </button>
      </section>

      {notices.length > 1 ? (
        <p className="text-xs text-slate-500 print:hidden">공고 {notices.length}건 · 판정 기록 {buildings.length}건</p>
      ) : null}

      <section className="rounded-xl border border-slate-200 bg-slate-50 p-5 text-sm text-slate-700 print:hidden">
        <h3 className="font-semibold text-slate-900">개인정보 안내</h3>
        <p className="mt-2 leading-relaxed">{PRIVACY_NOTICE}</p>
      </section>
    </div>
  );
}
