"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useDashboard } from "@/components/DashboardProvider";
import { csvEscape, downloadBlob, flat } from "@/lib/download";
import sampleExtract from "@/lib/sample-extract.json";
import type { Extracted, FieldValue } from "@/lib/types";

const ACCEPT = ".hwp,.hwpx,.pdf,.png,.jpg,.jpeg";
const ACCEPT_RE = /\.(hwp|hwpx|pdf|png|jpe?g)$/i;

const ROWS: { key: string; label: string }[] = [
  { key: "지자체", label: "지자체명" },
  { key: "사업명", label: "사업명" },
  { key: "연도", label: "연도" },
  { key: "시기", label: "시기" },
  { key: "사업유형", label: "사업유형" },
  { key: "경과연수", label: "경과연수" },
  { key: "층수", label: "층수" },
  { key: "연면적", label: "연면적" },
  { key: "용도조건", label: "허용 용도" },
  { key: "구조조건", label: "필수 구조" },
  { key: "제외대상", label: "제외 대상" },
  { key: "선정방식", label: "선정 방식" },
  { key: "우선순위기준", label: "우선순위 기준" },
  { key: "규모", label: "규모" },
  { key: "접수기간", label: "접수기간" },
  { key: "신청자격방법", label: "신청자격·방법" },
  { key: "지원내용", label: "지원내용" },
];

function asExtracted(data: Extracted & { error?: string }, fallbackName: string): Extracted {
  return {
    공고: data.공고 || fallbackName,
    모델: data.모델 || "",
    결과: data.결과 || {},
    skipped: data.skipped || [],
    readText: data.readText || "",
    mock: Boolean(data.mock),
    warnings: data.warnings || (data.error ? [data.error] : []),
  };
}

function needsConfirm(field: FieldValue | undefined): boolean {
  if (!field) return true;
  const empty = flat(field.value).trim() === "";
  return empty || field.evidence == null || String(field.evidence).trim() === "";
}

function checkTags(result: Extracted["결과"]): string[] {
  const raw = result["확인필요"]?.value;
  if (Array.isArray(raw)) return raw.map(String).filter(Boolean);
  if (raw == null || raw === "") return [];
  return [String(raw)];
}

export function NoticeAnalysisTab() {
  const { notices, setNotices, selectedNotice, setSelectedNotice, csrf, refreshCsrf } = useDashboard();
  const inputRef = useRef<HTMLInputElement>(null);
  const [files, setFiles] = useState<File[]>([]);
  const [dragOver, setDragOver] = useState(false);
  const [busy, setBusy] = useState(false);
  const [busyLabel, setBusyLabel] = useState("");
  const [progress, setProgress] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [selectedKey, setSelectedKey] = useState<string>(ROWS[0].key);

  const notice = notices[selectedNotice];

  useEffect(() => {
    if (!busy) return;
    setProgress(8);
    const id = window.setInterval(() => {
      setProgress((p) => (p >= 90 ? p : Math.min(90, p + 7)));
    }, 400);
    return () => window.clearInterval(id);
  }, [busy]);

  const addFiles = useCallback((list: FileList | File[]) => {
    const next = Array.from(list).filter((f) => ACCEPT_RE.test(f.name));
    setFiles((prev) => {
      const names = new Set(prev.map((f) => f.name + f.size));
      const extra = next.filter((f) => !names.has(f.name + f.size));
      return [...prev, ...extra].slice(0, 12);
    });
    if (next.length === 0 && Array.from(list).length) {
      setError("HWP, HWPX, PDF, PNG, JPG 파일만 올릴 수 있습니다.");
    } else {
      setError(null);
    }
  }, []);

  const startExtract = useCallback(async () => {
    if (!files.length) {
      setError("공고 파일을 올려 주세요.");
      return;
    }
    setBusy(true);
    setError(null);
    const queue = [...files];
    const added: Extracted[] = [];
    const failed: string[] = [];
    try {
      const token = csrf || (await refreshCsrf());
      for (let i = 0; i < queue.length; i++) {
        const file = queue[i];
        const label = file.name.replace(/\.[^.]+$/, "") || `공고${i + 1}`;
        setBusyLabel(`${i + 1}/${queue.length}`);
        setProgress(Math.min(90, Math.round(((i + 0.2) / queue.length) * 100)));
        const body = new FormData();
        body.set("name", label);
        body.append("files", file);
        const res = await fetch("/api/extract", {
          method: "POST",
          body,
          credentials: "same-origin",
          headers: token ? { "x-extract-csrf": token } : undefined,
        });
        let data: Extracted & { error?: string };
        try {
          data = (await res.json()) as Extracted & { error?: string };
        } catch {
          failed.push(`${label}: 추출 실패 (${res.status})`);
          continue;
        }
        if (!res.ok && !data.공고) {
          failed.push(`${label}: ${data.error || `추출 실패 (${res.status})`}`);
          continue;
        }
        added.push(asExtracted(data, label));
      }
      setProgress(100);
      if (added.length) {
        setNotices((prev) => {
          const next = [...prev, ...added];
          setSelectedNotice(next.length - 1);
          return next;
        });
        setFiles([]);
        if (inputRef.current) inputRef.current.value = "";
        setSelectedKey(ROWS[0].key);
      }
      if (failed.length) {
        setError(
          added.length
            ? `${added.length}건은 저장했고, 실패한 공고: ${failed.join(" · ")}`
            : failed.join(" · "),
        );
      } else if (!added.length) {
        setError("추출된 공고가 없습니다.");
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "추출에 실패했습니다.");
    } finally {
      setBusy(false);
      setBusyLabel("");
    }
  }, [files, setNotices, setSelectedNotice, csrf, refreshCsrf]);

  const loadSample = useCallback(() => {
    const extracted = asExtracted(sampleExtract as Extracted, "샘플");
    setNotices((prev) => {
      const next = [...prev, extracted];
      setSelectedNotice(next.length - 1);
      return next;
    });
    setSelectedKey(ROWS[0].key);
    setError(null);
  }, [setNotices, setSelectedNotice]);

  const selectedField = notice?.결과[selectedKey];
  const tags = notice ? checkTags(notice.결과) : [];

  const summaryCsv = useMemo(() => {
    if (!notices.length) return "";
    const cols = ["공고", ...ROWS.map((r) => r.label)];
    const lines = [cols.map(csvEscape).join(",")];
    for (const r of notices) {
      lines.push(
        [r.공고, ...ROWS.map((row) => csvEscape(flat(r.결과[row.key]?.value)))].join(","),
      );
    }
    return "\uFEFF" + lines.join("\n");
  }, [notices]);

  return (
    <div className="space-y-6">
      <section>
        <h2 className="text-lg font-semibold text-gov-900">공고문 분석 & 조건 추출</h2>
        <p className="mt-1 text-sm text-slate-600">
          파일 하나가 공고 하나입니다. 여러 파일을 올리면 공고마다 따로 추출하고, 항목을 누르면 원문 근거를 옆에 보여 줍니다.
        </p>
      </section>

      <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
        <div
          className={`flex flex-col items-center justify-center rounded-xl border-2 border-dashed px-4 py-10 text-center transition ${
            dragOver ? "border-gov-600 bg-sky-50" : "border-slate-300 bg-slate-50/70"
          }`}
          onDragOver={(e) => {
            e.preventDefault();
            setDragOver(true);
          }}
          onDragLeave={() => setDragOver(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDragOver(false);
            addFiles(e.dataTransfer.files);
          }}
        >
          <p className="text-sm font-medium text-slate-800">공고문 파일을 여기에 놓으세요</p>
          <p className="mt-1 text-xs text-slate-500">
            HWP · HWPX · PDF · PNG · JPG · 파일 하나 = 공고 하나 (파일당 12MB)
          </p>
          <div className="mt-4 flex flex-wrap items-center justify-center gap-2">
            <button
              type="button"
              className="rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm font-semibold text-slate-800 hover:bg-slate-100"
              onClick={() => inputRef.current?.click()}
            >
              파일 선택
            </button>
            <button
              type="button"
              className="rounded-lg bg-gov-700 px-4 py-2 text-sm font-semibold text-white hover:bg-gov-800 disabled:opacity-50"
              onClick={() => void startExtract()}
              disabled={busy || !files.length}
            >
              LLM 조건 추출 시작
            </button>
          </div>
          <input
            ref={inputRef}
            className="sr-only"
            type="file"
            accept={ACCEPT}
            multiple
            onChange={(e) => addFiles(e.target.files ?? [])}
          />
        </div>

        {files.length ? (
          <ul className="mt-4 divide-y divide-slate-100 rounded-lg border border-slate-100">
            {files.map((f) => (
              <li key={f.name + f.size} className="flex items-center justify-between gap-3 px-3 py-2 text-sm">
                <span className="truncate">{f.name}</span>
                <button
                  type="button"
                  className="shrink-0 text-gov-700"
                  onClick={() => setFiles((all) => all.filter((x) => x !== f))}
                >
                  빼기
                </button>
              </li>
            ))}
          </ul>
        ) : null}

        {busy ? (
          <div className="mt-5 rounded-lg border border-sky-100 bg-sky-50 px-4 py-4" role="status" aria-live="polite">
            <div className="flex items-center gap-3">
              <span className="inline-block h-5 w-5 animate-spin rounded-full border-2 border-gov-600 border-t-transparent" />
              <p className="text-sm font-medium text-gov-900">
                Claude API 기반 공고문 조건 분석 중...
                {busyLabel ? ` (${busyLabel})` : ""}
              </p>
            </div>
            <div className="mt-3 h-2 overflow-hidden rounded-full bg-white">
              <div className="h-full rounded-full bg-gov-600 transition-all" style={{ width: `${progress}%` }} />
            </div>
            <p className="mt-1 text-right text-xs text-slate-500">{progress}%</p>
          </div>
        ) : null}

        {error ? (
          <p className="mt-3 text-sm text-red-700" role="alert">
            {error}
          </p>
        ) : null}

        <p className="mt-4 text-xs text-slate-500">
          화면만 확인하려면{" "}
          <button type="button" className="font-medium text-gov-700 underline" onClick={loadSample}>
            샘플 JSON
          </button>
          을 불러올 수 있습니다.
        </p>
      </section>

      {notices.length ? (
        <section className="flex flex-wrap items-center justify-between gap-3">
          <label className="flex items-center gap-2 text-sm">
            <span className="font-medium text-slate-700">공고</span>
            <select
              className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm"
              value={selectedNotice}
              onChange={(e) => {
                setSelectedNotice(Number(e.target.value));
                setSelectedKey(ROWS[0].key);
              }}
            >
              {notices.map((n, i) => (
                <option key={n.공고 + i} value={i}>
                  {n.공고}
                  {n.mock ? " (샘플)" : ""}
                </option>
              ))}
            </select>
          </label>
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
        </section>
      ) : null}

      {notice ? (
        <section className="grid gap-4 lg:grid-cols-5">
          <div className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm lg:col-span-3">
            <div className="border-b border-slate-100 px-4 py-3">
              <h3 className="font-semibold text-gov-900">{notice.공고}</h3>
              <p className="text-xs text-slate-500">모델 {notice.모델}</p>
              {tags.length ? (
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {tags.map((t) => (
                    <span
                      key={t}
                      className="inline-flex rounded-full bg-amber-100 px-2 py-0.5 text-xs font-semibold text-amber-950 ring-1 ring-orange-300"
                    >
                      확인필요 · {t}
                    </span>
                  ))}
                </div>
              ) : null}
            </div>
            {notice.warnings?.length ? (
              <ul className="space-y-1 bg-amber-50 px-4 py-3 text-sm text-amber-900">
                {notice.warnings.map((w) => (
                  <li key={w}>{w}</li>
                ))}
              </ul>
            ) : null}
            <table className="min-w-full text-left text-sm">
              <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
                <tr>
                  <th className="px-4 py-2 font-medium">항목</th>
                  <th className="px-4 py-2 font-medium">값</th>
                </tr>
              </thead>
              <tbody>
                {ROWS.map((row) => {
                  const field = notice.결과[row.key];
                  const confirm = needsConfirm(field);
                  const active = selectedKey === row.key;
                  return (
                    <tr
                      key={row.key}
                      className={`cursor-pointer border-t border-slate-100 align-top ${
                        active ? "bg-sky-50" : "hover:bg-slate-50"
                      }`}
                      onClick={() => setSelectedKey(row.key)}
                    >
                      <td className="whitespace-nowrap px-4 py-2.5 font-medium text-slate-800">
                        <span className="flex items-center gap-2">
                          {row.label}
                          {confirm ? (
                            <span className="inline-flex rounded bg-orange-100 px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wide text-orange-800 ring-1 ring-orange-300">
                              확인필요
                            </span>
                          ) : null}
                        </span>
                      </td>
                      <td className="px-4 py-2.5">{flat(field?.value) || "—"}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          <aside className="lg:col-span-2">
            <div className="sticky top-4 rounded-xl border border-orange-200 bg-orange-50/80 p-5 shadow-sm">
              <p className="text-xs font-semibold tracking-wide text-orange-800">원문 근거</p>
              <h3 className="mt-1 text-base font-semibold text-gov-900">
                {ROWS.find((r) => r.key === selectedKey)?.label}
              </h3>
              {selectedField?.evidence ? (
                <blockquote className="mt-3 border-l-4 border-orange-400 bg-white px-3 py-3 text-sm leading-relaxed text-slate-800">
                  “{selectedField.evidence}”
                </blockquote>
              ) : (
                <p className="mt-3 text-sm text-slate-600">이 항목의 원문 인용이 없습니다. 공고문을 다시 확인해 주세요.</p>
              )}
              <p className="mt-4 text-xs text-slate-500">왼쪽 표의 항목을 누르면 근거가 바뀝니다.</p>
            </div>
          </aside>
        </section>
      ) : null}
    </div>
  );
}
