"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

type FieldValue = { value: unknown; evidence: string | null };

type Extracted = {
  공고: string;
  모델: string;
  결과: Record<string, FieldValue>;
  skipped: string[];
  readText: string;
  mock: boolean;
  warnings: string[];
  error?: string;
};

type Draft = { id: string; name: string; files: File[] };

const STORE = "notice-extract-results-v1";

function flat(v: unknown): string {
  if (Array.isArray(v)) return v.map(String).join(" / ");
  return v == null ? "" : String(v);
}

function csvEscape(s: string): string {
  if (/[",\n]/.test(s)) return `"${s.replace(/"/g, '""')}"`;
  return s;
}

function downloadBlob(filename: string, blob: Blob) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

export default function Page() {
  const [drafts, setDrafts] = useState<Draft[]>([]);
  const [name, setName] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [results, setResults] = useState<Extracted[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState<{ mock: boolean; model: string; viewer: string; simulated: boolean } | null>(
    null,
  );
  const [openText, setOpenText] = useState<Record<string, boolean>>({});

  useEffect(() => {
    try {
      const raw = sessionStorage.getItem(STORE);
      if (raw) setResults(JSON.parse(raw) as Extracted[]);
    } catch {
      /* ignore */
    }
    fetch("/api/status", { cache: "no-store" })
      .then(async (r) => {
        if (!r.ok) throw new Error("status");
        return r.json();
      })
      .then(setStatus)
      .catch(() => setStatus(null));
  }, []);

  useEffect(() => {
    try {
      sessionStorage.setItem(STORE, JSON.stringify(results));
    } catch {
      /* ignore */
    }
  }, [results]);

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
    const next: Extracted[] = [...results];
    try {
      for (const draft of drafts) {
        const body = new FormData();
        body.set("name", draft.name);
        for (const f of draft.files) body.append("files", f);
        const res = await fetch("/api/extract", { method: "POST", body });
        const data = (await res.json()) as Extracted & { error?: string };
        if (!res.ok && !data.공고) {
          throw new Error(data.error || `추출 실패 (${res.status})`);
        }
        next.push({
          공고: data.공고 || draft.name,
          모델: data.모델 || "",
          결과: data.결과 || {},
          skipped: data.skipped || [],
          readText: data.readText || "",
          mock: Boolean(data.mock),
          warnings: data.warnings || (data.error ? [data.error] : []),
        });
        setResults([...next]);
      }
      setDrafts([]);
    } catch (e) {
      setError(e instanceof Error ? e.message : "추출에 실패했습니다.");
    } finally {
      setBusy(false);
    }
  }, [drafts, results]);

  const summaryCsv = useMemo(() => {
    if (!results.length) return "";
    const cols = ["공고", ...Object.keys(results[0].결과)];
    const lines = [cols.map(csvEscape).join(",")];
    for (const r of results) {
      const row = [r.공고, ...cols.slice(1).map((c) => csvEscape(flat(r.결과[c]?.value)))];
      lines.push(row.join(","));
    }
    return "\uFEFF" + lines.join("\n");
  }, [results]);

  return (
    <main>
      <div className="kicker">안전점검 공고</div>
      <h1>공고 조건 추출기</h1>
      <p className="lede">
        공고 하나마다 파일을 올립니다. 앞면·뒷면처럼 여러 장이면 한 공고로 묶습니다. 지원 조건과 원문 근거를 뽑고, 공고별
        JSON과 요약 CSV를 받을 수 있습니다.
      </p>

      {status?.mock && (
        <div className="banner" role="status">
          지금은 샘플 데이터로 동작합니다. Anthropic API 키가 이 환경에 없습니다. 게시된 앱의 비밀 값에{" "}
          <code>ANTHROPIC_API_KEY</code>를 넣으면 실제 추출이 됩니다.
          {status.simulated ? " 미리보기 사용자는 모의 로그인입니다." : null}
        </div>
      )}

      <section className="card">
        <h2>공고 올리기</h2>
        <label htmlFor="notice-name">공고 이름</label>
        <input
          id="notice-name"
          type="text"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="예: 대전중구_2026하반기"
        />
        <label htmlFor="files">파일 (hwp, hwpx, docx, html, pdf, png, jpg, webp, txt)</label>
        <input
          id="files"
          type="file"
          multiple
          onChange={(e) => setFiles(Array.from(e.target.files ?? []))}
        />
        <p className="hint">한 공고에 파일 12개·각 12MB·합계 24MB까지입니다.</p>
        <div className="toolbar">
          <button type="button" onClick={addDraft}>
            공고로 묶기
          </button>
          <button type="button" className="secondary" onClick={extractAll} disabled={busy || !drafts.length}>
            {busy ? "추출 중…" : "조건 추출하기"}
          </button>
        </div>
        {error ? (
          <p className="error" role="alert">
            {error}
          </p>
        ) : null}
        {drafts.length ? (
          <ul className="notice-list">
            {drafts.map((d) => (
              <li key={d.id}>
                <div>
                  <strong>{d.name}</strong>
                  <div className="files">{d.files.map((f) => f.name).join(", ")}</div>
                </div>
                <button
                  type="button"
                  className="ghost"
                  onClick={() => setDrafts((all) => all.filter((x) => x.id !== d.id))}
                >
                  빼기
                </button>
              </li>
            ))}
          </ul>
        ) : (
          <p className="hint">아직 대기 중인 공고가 없습니다.</p>
        )}
      </section>

      {results.length ? (
        <section className="card">
          <h2>결과 {results.length}건</h2>
          <div className="toolbar">
            <button
              type="button"
              className="secondary"
              onClick={() =>
                downloadBlob("요약.csv", new Blob([summaryCsv], { type: "text/csv;charset=utf-8" }))
              }
            >
              요약 CSV 내려받기
            </button>
            <button type="button" className="ghost" onClick={() => setResults([])}>
              세션 결과 지우기
            </button>
          </div>
        </section>
      ) : null}

      {results.map((r, idx) => (
        <article className="card" key={`${r.공고}-${idx}`}>
          <h2>{r.공고}</h2>
          <p className="hint">
            모델 {r.모델}
            {r.mock ? " · 샘플" : ""}
          </p>
          {r.warnings?.length ? (
            <ul className="skipped">
              {r.warnings.map((w) => (
                <li key={w}>{w}</li>
              ))}
            </ul>
          ) : null}
          {r.skipped?.length ? (
            <div className="skipped">
              <strong>건너뛴 파일</strong>
              <ul>
                {r.skipped.map((s) => (
                  <li key={s}>{s}</li>
                ))}
              </ul>
            </div>
          ) : null}
          <dl>
            {Object.entries(r.결과).map(([k, v]) => (
              <div className="field" key={k}>
                <dt>{k}</dt>
                <dd>{flat(v.value) || "—"}</dd>
                {v.evidence ? <dd className="evidence">근거: {v.evidence}</dd> : null}
              </div>
            ))}
          </dl>
          <div className="toolbar">
            <button
              type="button"
              className="secondary"
              onClick={() =>
                downloadBlob(
                  `${r.공고}.json`,
                  new Blob(
                    [JSON.stringify({ 공고: r.공고, 모델: r.모델, 결과: r.결과 }, null, 2)],
                    { type: "application/json;charset=utf-8" },
                  ),
                )
              }
            >
              JSON 내려받기
            </button>
            {r.readText ? (
              <button
                type="button"
                className="ghost"
                onClick={() => setOpenText((o) => ({ ...o, [r.공고 + idx]: !o[r.공고 + idx] }))}
              >
                {openText[r.공고 + idx] ? "읽은 내용 닫기" : "읽은 내용 보기"}
              </button>
            ) : null}
          </div>
          {openText[r.공고 + idx] && r.readText ? <pre className="read-text">{r.readText}</pre> : null}
        </article>
      ))}
    </main>
  );
}
