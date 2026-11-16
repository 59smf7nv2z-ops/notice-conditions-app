"use client";

import { useMemo, useState } from "react";
import { useDashboard } from "@/components/DashboardProvider";
import { csvEscape, downloadBlob } from "@/lib/download";
import { buildGuide, candidatesOf } from "@/lib/guide";

export function GuideReportTab() {
  const { notice, notices, selectedNotice, setSelectedNotice, buildings } = useDashboard();
  const [edited, setEdited] = useState<string | null>(null);
  const generated = useMemo(() => buildGuide(notice, buildings), [notice, buildings]);
  const text = edited ?? generated;
  const candidates = candidatesOf(buildings);

  const reportCsv = useMemo(() => {
    const cols = ["주소", "소유자", "공고", "1차판정", "경과연수", "층수", "연면적", "용도", "구조"];
    const lines = [cols.map(csvEscape).join(",")];
    for (const b of buildings) {
      lines.push(
        [b.address, b.ownerHint, b.noticeName, b.overall, b.ageYears, b.floors, b.floorArea, b.use, b.structure]
          .map(csvEscape)
          .join(","),
      );
    }
    return "\uFEFF" + lines.join("\n");
  }, [buildings]);

  return (
    <div className="space-y-6">
      <section>
        <h2 className="text-lg font-semibold text-gov-900">맞춤형 안내문 및 결과 리포트</h2>
        <p className="mt-1 text-sm text-slate-600">
          1차 해당·확인필요 건을 바탕으로 안내문 초안을 만들고, 판정 결과를 CSV·JSON으로 내려받습니다. 발송 전 담당자가
          문안을 검수하세요.
        </p>
      </section>

      <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
        <label className="text-sm font-medium" htmlFor="guide-notice">
          안내문에 쓸 공고
        </label>
        <select
          id="guide-notice"
          className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
          value={selectedNotice}
          onChange={(e) => {
            setSelectedNotice(Number(e.target.value));
            setEdited(null);
          }}
          disabled={!notices.length}
        >
          {notices.length ? (
            notices.map((n, i) => (
              <option key={n.공고 + i} value={i}>
                {n.공고}
              </option>
            ))
          ) : (
            <option value={0}>추출된 공고 없음</option>
          )}
        </select>
        <p className="mt-3 text-sm text-slate-600">
          1차 후보자 {candidates.length}건 (해당·확인필요) · 전체 판정 {buildings.length}건
        </p>
        <div className="mt-3 flex flex-wrap gap-2">
          <button
            type="button"
            className="rounded-lg bg-gov-700 px-4 py-2 text-sm font-semibold text-white"
            onClick={() => setEdited(null)}
          >
            초안 다시 만들기
          </button>
          <button
            type="button"
            className="rounded-lg bg-slate-100 px-3 py-2 text-sm font-medium"
            onClick={() => downloadBlob("안내문.txt", new Blob([text], { type: "text/plain;charset=utf-8" }))}
          >
            안내문 TXT
          </button>
          <button
            type="button"
            className="rounded-lg bg-slate-100 px-3 py-2 text-sm font-medium"
            onClick={() => downloadBlob("1차판정.csv", new Blob([reportCsv], { type: "text/csv;charset=utf-8" }))}
          >
            판정 CSV
          </button>
          <button
            type="button"
            className="rounded-lg bg-slate-100 px-3 py-2 text-sm font-medium"
            onClick={() =>
              downloadBlob(
                "1차판정.json",
                new Blob([JSON.stringify({ 공고: notice?.공고 ?? null, 건물: buildings }, null, 2)], {
                  type: "application/json;charset=utf-8",
                }),
              )
            }
          >
            판정 JSON
          </button>
        </div>
      </section>

      {candidates.length ? (
        <ul className="rounded-xl border border-slate-200 bg-white p-5 text-sm shadow-sm">
          {candidates.map((c) => (
            <li key={c.id} className="border-t border-slate-100 py-2 first:border-t-0">
              <span className="font-medium">{c.address}</span>
              <span className="ml-2 text-slate-500">{c.overall}</span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="rounded-xl border border-dashed border-slate-300 bg-white px-5 py-8 text-center text-sm text-slate-500">
          안내 대상이 없습니다. 건물 정보 대조 탭에서 1차 판정을 먼저 하세요.
        </p>
      )}

      <label className="block text-sm font-medium" htmlFor="guide-body">
        안내문 초안
      </label>
      <textarea
        id="guide-body"
        className="min-h-[28rem] w-full rounded-xl border border-slate-200 bg-white p-4 font-mono text-sm leading-relaxed shadow-sm outline-none ring-gov-600 focus:ring-2"
        value={text}
        onChange={(e) => setEdited(e.target.value)}
      />
    </div>
  );
}
