"use client";

import { useCallback, useMemo, useState } from "react";
import { useDashboard } from "@/components/DashboardProvider";
import { csvEscape, downloadBlob, flat } from "@/lib/download";
import type { Extracted } from "@/lib/types";

type Draft = { id: string; name: string; files: File[] };

export function NoticeExtractTab() {
  const { notices, setNotices } = useDashboard();
  const [drafts, setDrafts] = useState<Draft[]>([]);
  const [name, setName] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [openText, setOpenText] = useState<Record<string, boolean>>({});

  const addDraft = useCallback(() => {
    setError(null);
    if (!files.length) {
      setError("파일을 선택해 주세요.");
      return;
    }
    const label = name.trim() || files[0].name.replace(/\.[^.]+$/, "");
    setDrafts((d) => [...d, { id: crypto.randomUUID(), name: label, files }]);
    setName("");
    setFiles([]);
    const input = document.getElementById("files") as HTMLInputElement | null;
    if (input) input.value = "";
  }, [files, name]);

  const extractAll = useCallback(async () => {
    if (!drafts.length) {
      setError("공고를 먼저 추가해 주세요.");
      return;
    }
    setBusy(true);
    setError(null);
    const next: Extracted[] = [...notices];
    try {
      for (const draft of drafts) {
        const body = new FormData();
        body.set("name", draft.name);
        for (const f of draft.files) body.append("files", f);
        const res = await fetch("/api/extract", {
          method: "POST",
          body,
          credentials: "same-origin",
          headers: { "x-extract-csrf": (await fetch("/api/status", { cache: "no-store", credentials: "same-origin" }).then((r) => r.json()) as { csrf?: string }).csrf || "" },
        });
        let data: Extracted & { error?: string };
        try {
          data = (await res.json()) as Extracted & { error?: string };
        } catch {
          throw new Error(`추출 실패 (${res.status})`);
        }
        if (!res.ok && !data.공고) throw new Error(data.error || `추출 실패 (${res.status})`);
        next.push({
          공고: data.공고 || draft.name,
          모델: data.모델 || "",
          결과: data.결과 || {},
          skipped: data.skipped || [],
          readText: data.readText || "",
          mock: Boolean(data.mock),
          warnings: data.warnings || (data.error ? [data.error] : []),
        });
        setNotices([...next]);
      }
      setDrafts([]);
    } catch (e) {
      setError(e instanceof Error ? e.message : "추출에 실패했습니다.");
    } finally {
      setBusy(false);
    }
  }, [drafts, notices, setNotices]);

  const summaryCsv = useMemo(() => {
    if (!notices.length) return "";
    const cols = ["공고", ...Object.keys(notices[0].결과)];
    const lines = [cols.map(csvEscape).join(",")];
    for (const r of notices) {
      lines.push([r.공고, ...cols.slice(1).map((c) => csvEscape(flat(r.결과[c]?.value)))].join(","));
    }
    return "\uFEFF" + lines.join("\n");
  }, [notices]);

  return (
    <div className="space-y-6">
      <section>
        <h2 className="text-lg font-semibold text-gov-900">공고문 분석 & 조건 추출</h2>
        <p className="mt-1 text-sm text-slate-600">
          공고 하나마다 파일을 올립니다. 앞면·뒷면처럼 여러 장이면 한 공고로 묶은 뒤 지원 조건과 원문 근거를 표로
          확인합니다.
        </p>
      </section>

      <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
        <h3 className="font-semibold text-slate-900">공고 올리기</h3>
        <label className="mt-4 block text-sm font-medium" htmlFor="notice-name">
          공고 이름
        </label>
        <input
          id="notice-name"
          className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none ring-gov-600 focus:ring-2"
          type="text"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="예: 대전중구_2026하반기"
        />
        <label className="mt-4 block text-sm font-medium" htmlFor="files">
          파일 (hwp, hwpx, docx, html, pdf, png, jpg, webp, txt)
        </label>
        <input id="files" className="mt-1 block w-full text-sm" type="file" multiple onChange={(e) => setFiles(Array.from(e.target.files ?? []))} />
        <p className="mt-2 text-xs text-slate-500">한 공고에 파일 12개·각 12MB·합계 24MB까지입니다.</p>
        <div className="mt-4 flex flex-wrap gap-2">
          <button
            type="button"
            className="rounded-lg bg-gov-700 px-4 py-2 text-sm font-semibold text-white hover:bg-gov-800"
            onClick={addDraft}
          >
            공고로 묶기
          </button>
          <button
            type="button"
            className="rounded-lg bg-slate-100 px-4 py-2 text-sm font-semibold text-slate-800 hover:bg-slate-200 disabled:opacity-50"
            onClick={extractAll}
            disabled={busy || !drafts.length}
          >
            {busy ? "추출 중…" : "조건 추출하기"}
          </button>
        </div>
        {error ? (
          <p className="mt-3 text-sm text-red-700" role="alert">
            {error}
          </p>
        ) : null}
        {drafts.length ? (
          <ul className="mt-4 divide-y divide-slate-100 border-t border-slate-100">
            {drafts.map((d) => (
              <li key={d.id} className="flex items-start justify-between gap-3 py-3">
                <div>
                  <p className="font-medium">{d.name}</p>
                  <p className="text-xs text-slate-500">{d.files.map((f) => f.name).join(", ")}</p>
                </div>
                <button type="button" className="text-sm text-gov-700" onClick={() => setDrafts((all) => all.filter((x) => x.id !== d.id))}>
                  빼기
                </button>
              </li>
            ))}
          </ul>
        ) : (
          <p className="mt-3 text-sm text-slate-500">아직 대기 중인 공고가 없습니다.</p>
        )}
      </section>

      {notices.length ? (
        <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h3 className="font-semibold">추출 결과 {notices.length}건</h3>
            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                className="rounded-lg bg-slate-100 px-3 py-1.5 text-sm font-medium"
                onClick={() => downloadBlob("요약.csv", new Blob([summaryCsv], { type: "text/csv;charset=utf-8" }))}
              >
                요약 CSV
              </button>
              <button type="button" className="text-sm text-gov-700" onClick={() => setNotices([])}>
                세션 결과 지우기
              </button>
            </div>
          </div>
        </section>
      ) : null}

      {notices.map((r, idx) => (
        <article key={`${r.공고}-${idx}`} className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
          <div className="border-b border-slate-100 px-5 py-4">
            <h3 className="font-semibold text-gov-900">{r.공고}</h3>
            <p className="text-xs text-slate-500">
              모델 {r.모델}
              {r.mock ? " · 샘플" : ""}
            </p>
          </div>
          {r.warnings?.length ? (
            <ul className="space-y-1 bg-amber-50 px-5 py-3 text-sm text-amber-900">
              {r.warnings.map((w) => (
                <li key={w}>{w}</li>
              ))}
            </ul>
          ) : null}
          {r.skipped?.length ? (
            <div className="bg-orange-50 px-5 py-3 text-sm text-orange-900">
              <p className="font-medium">건너뛴 파일</p>
              <ul className="mt-1 list-disc pl-5">
                {r.skipped.map((s) => (
                  <li key={s}>{s}</li>
                ))}
              </ul>
            </div>
          ) : null}
          <div className="overflow-x-auto">
            <table className="min-w-full text-left text-sm">
              <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
                <tr>
                  <th className="px-5 py-2 font-medium">항목</th>
                  <th className="px-5 py-2 font-medium">값</th>
                  <th className="px-5 py-2 font-medium">원문 근거</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(r.결과).map(([k, v]) => (
                  <tr key={k} className="border-t border-slate-100 align-top">
                    <td className="whitespace-nowrap px-5 py-2.5 font-medium text-slate-800">{k}</td>
                    <td className="px-5 py-2.5">{flat(v.value) || "—"}</td>
                    <td className="px-5 py-2.5 text-slate-500">{v.evidence || "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="flex flex-wrap gap-2 border-t border-slate-100 px-5 py-3">
            <button
              type="button"
              className="rounded-lg bg-slate-100 px-3 py-1.5 text-sm font-medium"
              onClick={() =>
                downloadBlob(
                  `${r.공고}.json`,
                  new Blob([JSON.stringify({ 공고: r.공고, 모델: r.모델, 결과: r.결과 }, null, 2)], {
                    type: "application/json;charset=utf-8",
                  }),
                )
              }
            >
              JSON 내려받기
            </button>
            {r.readText ? (
              <button
                type="button"
                className="text-sm text-gov-700"
                onClick={() => setOpenText((o) => ({ ...o, [r.공고 + idx]: !o[r.공고 + idx] }))}
              >
                {openText[r.공고 + idx] ? "읽은 내용 닫기" : "읽은 내용 보기"}
              </button>
            ) : null}
          </div>
          {openText[r.공고 + idx] && r.readText ? (
            <pre className="max-h-72 overflow-auto whitespace-pre-wrap bg-slate-50 px-5 py-3 text-xs text-slate-700">
              {r.readText}
            </pre>
          ) : null}
        </article>
      ))}
    </div>
  );
}
