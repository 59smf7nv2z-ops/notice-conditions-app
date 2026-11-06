"use client";

import { useMemo, useState } from "react";
import { useDashboard } from "@/components/DashboardProvider";
import { judgeBuilding, needsCheckItems } from "@/lib/compare";
import { SAMPLE_BUILDINGS, mockRegistryLookup, yearsSince, type RegistryFill } from "@/lib/registry";
import sampleExtract from "@/lib/sample-extract.json";
import type { Extracted, Verdict } from "@/lib/types";

const empty: RegistryFill = {
  address: "",
  ownerHint: "",
  approvalDate: "",
  ageYears: "",
  floors: "",
  basementFloors: "",
  floorArea: "",
  use: "",
  structure: "",
};

function tagLabel(v: Verdict): string {
  if (v === "해당") return "일치";
  if (v === "비해당") return "미달";
  return "확인필요";
}

function Badge({ v, large }: { v: Verdict; large?: boolean }) {
  const text =
    v === "해당" ? "해당(적합)" : v === "비해당" ? "비해당(불적합)" : "확인필요(수동검토)";
  const cls =
    v === "해당"
      ? "bg-emerald-100 text-emerald-900 ring-emerald-300"
      : v === "비해당"
        ? "bg-rose-100 text-rose-900 ring-rose-300"
        : "bg-orange-100 text-orange-950 ring-orange-300";
  return (
    <span
      className={`inline-flex items-center rounded-full font-bold ring-1 ${cls} ${
        large ? "px-4 py-1.5 text-base" : "px-2 py-0.5 text-xs"
      }`}
    >
      {text}
    </span>
  );
}

function Tag({ v }: { v: Verdict }) {
  const label = tagLabel(v);
  const cls =
    v === "해당"
      ? "bg-emerald-50 text-emerald-800 ring-emerald-200"
      : v === "비해당"
        ? "bg-rose-50 text-rose-800 ring-rose-200"
        : "bg-amber-50 text-amber-900 ring-amber-200";
  return <span className={`inline-flex rounded-full px-2 py-0.5 text-xs font-semibold ring-1 ${cls}`}>{label}</span>;
}

export function BuildingMatchTab() {
  const { notices, selectedNotice, setSelectedNotice, notice, setNotices } = useDashboard();
  const [form, setForm] = useState<RegistryFill>(empty);
  const [query, setQuery] = useState("");
  const [looking, setLooking] = useState(false);
  const [hint, setHint] = useState<string | null>(null);

  const activeNotice = notice ?? (sampleExtract as Extracted);

  const judged = useMemo(() => judgeBuilding(activeNotice, form), [activeNotice, form]);
  const checklist = needsCheckItems(activeNotice);

  function applyFill(next: RegistryFill) {
    const filled = { ...next, ageYears: next.ageYears || yearsSince(next.approvalDate) };
    setForm(filled);
    setQuery(filled.address);
    setHint(null);
  }

  function loadSampleNoticeIfEmpty() {
    if (notices.length) return;
    setNotices([sampleExtract as Extracted]);
    setSelectedNotice(0);
  }

  async function lookupRegistry() {
    const q = query.trim() || form.address.trim();
    if (!q) {
      setHint("조회할 주소를 입력해 주세요.");
      return;
    }
    setLooking(true);
    setHint(null);
    await new Promise((r) => window.setTimeout(r, 350));
    const row = mockRegistryLookup(q);
    setLooking(false);
    if (!row) {
      setHint("모의 대장에서 해당 주소를 찾지 못했습니다.");
      return;
    }
    loadSampleNoticeIfEmpty();
    applyFill(row);
    setHint("모의 건축물대장 결과를 폼에 채웠습니다.");
  }

  function loadSample(kind: keyof typeof SAMPLE_BUILDINGS) {
    loadSampleNoticeIfEmpty();
    applyFill(SAMPLE_BUILDINGS[kind]);
    setHint(`${kind} 샘플 건물 데이터를 불러왔습니다.`);
  }

  function setApproval(iso: string) {
    setForm((f) => ({ ...f, approvalDate: iso, ageYears: yearsSince(iso) }));
  }

  const hasInput = Boolean(form.address.trim() || form.ageYears || form.floors || form.floorArea || form.use || form.structure);

  return (
    <div className="space-y-6">
      <section>
        <h2 className="text-lg font-semibold text-gov-900">건물 정보 대조 & 1차 판정</h2>
        <p className="mt-1 text-sm text-slate-600">
          주소를 조회하거나 대장을 직접 입력하면, 공고문 분석 탭에서 뽑은 조건과 바로 대조합니다.
        </p>
      </section>

      <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
        <label className="text-sm font-medium" htmlFor="notice-select">
          대조할 공고
        </label>
        <select
          id="notice-select"
          className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
          value={notices.length ? selectedNotice : 0}
          onChange={(e) => setSelectedNotice(Number(e.target.value))}
          disabled={!notices.length}
        >
          {notices.length ? (
            notices.map((n, i) => (
              <option key={n.공고 + i} value={i}>
                {n.공고}
              </option>
            ))
          ) : (
            <option value={0}>샘플 공고(대전중구) · 조건 추출 전이면 이 기준으로 미리 봅니다</option>
          )}
        </select>

        <div className="mt-4 flex flex-col gap-2 sm:flex-row">
          <input
            id="address-search"
            className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none ring-gov-600 focus:ring-2"
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              setForm((f) => ({ ...f, address: e.target.value }));
            }}
            placeholder="주소 검색 · 예: 대전광역시 중구 은행동 12-3"
          />
          <button
            type="button"
            className="shrink-0 rounded-lg bg-gov-700 px-4 py-2 text-sm font-semibold text-white hover:bg-gov-800 disabled:opacity-50"
            onClick={() => void lookupRegistry()}
            disabled={looking}
          >
            {looking ? "조회 중…" : "건축물대장 조회(샘플)"}
          </button>
        </div>
        <p className="mt-2 text-xs text-slate-500">실제 세움터 연동이 아니라 주소 키워드로 모의 대장을 채웁니다.</p>

        <div className="mt-4 grid gap-3 sm:grid-cols-2">
          <Field
            label="사용승인일"
            id="approval"
            type="date"
            value={form.approvalDate}
            onChange={setApproval}
          />
          <Field
            label="계산 경과연수(년)"
            id="age"
            value={form.ageYears}
            onChange={(v) => setForm((f) => ({ ...f, ageYears: v }))}
            placeholder="사용승인일에서 자동 계산"
          />
          <Field
            label="지상 층수"
            id="floors"
            value={form.floors}
            onChange={(v) => setForm((f) => ({ ...f, floors: v }))}
            placeholder="예: 2"
          />
          <Field
            label="지하 층수"
            id="basement"
            value={form.basementFloors}
            onChange={(v) => setForm((f) => ({ ...f, basementFloors: v }))}
            placeholder="예: 0"
          />
          <Field
            label="연면적(㎡)"
            id="area"
            value={form.floorArea}
            onChange={(v) => setForm((f) => ({ ...f, floorArea: v }))}
            placeholder="예: 280"
          />
          <Field
            label="용도"
            id="use"
            value={form.use}
            onChange={(v) => setForm((f) => ({ ...f, use: v }))}
            placeholder="예: 주택"
          />
          <Field
            label="구조"
            id="structure"
            value={form.structure}
            onChange={(v) => setForm((f) => ({ ...f, structure: v }))}
            placeholder="예: 조적조"
          />
        </div>

        <div className="mt-4 flex flex-wrap gap-2">
          <button
            type="button"
            className="rounded-lg bg-emerald-700 px-3 py-2 text-sm font-semibold text-white hover:bg-emerald-800"
            onClick={() => loadSample("해당")}
          >
            샘플 건물 데이터 불러오기 · 해당
          </button>
          <button
            type="button"
            className="rounded-lg bg-rose-700 px-3 py-2 text-sm font-semibold text-white hover:bg-rose-800"
            onClick={() => loadSample("비해당")}
          >
            샘플 건물 데이터 불러오기 · 비해당
          </button>
          <button
            type="button"
            className="rounded-lg bg-orange-600 px-3 py-2 text-sm font-semibold text-white hover:bg-orange-700"
            onClick={() => loadSample("확인필요")}
          >
            샘플 건물 데이터 불러오기 · 확인필요
          </button>
        </div>
        {hint ? <p className="mt-3 text-sm text-gov-800">{hint}</p> : null}
      </section>

      {hasInput ? (
        <section className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
          <div className="flex flex-wrap items-start justify-between gap-3 border-b border-slate-100 px-5 py-4">
            <div>
              <p className="font-semibold text-gov-900">{form.address || "주소 미입력"}</p>
              <p className="text-xs text-slate-500">
                {activeNotice.공고}
                {form.ownerHint ? ` · ${form.ownerHint}` : ""}
                {form.basementFloors !== "" ? ` · 지하 ${form.basementFloors}층` : ""}
              </p>
            </div>
            <Badge v={judged.overall} large />
          </div>
          <div className="overflow-x-auto">
            <table className="min-w-full text-left text-sm">
              <thead className="bg-slate-50 text-xs text-slate-500">
                <tr>
                  <th className="px-5 py-2 font-medium">항목</th>
                  <th className="px-5 py-2 font-medium">공고 기준</th>
                  <th className="px-5 py-2 font-medium">건물 값</th>
                  <th className="px-5 py-2 font-medium">태그</th>
                  <th className="px-5 py-2 font-medium">메모</th>
                </tr>
              </thead>
              <tbody>
                {judged.checks.map((c) => (
                  <tr key={c.item} className="border-t border-slate-100 align-top">
                    <td className="px-5 py-2 font-medium">{c.item}</td>
                    <td className="px-5 py-2">{c.condition}</td>
                    <td className="px-5 py-2">{c.building}</td>
                    <td className="px-5 py-2">
                      <Tag v={c.verdict} />
                    </td>
                    <td className="px-5 py-2 text-slate-500">{c.note}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      ) : (
        <p className="text-sm text-slate-500">샘플 버튼을 누르거나 대장을 입력하면 즉시 대조 표가 열립니다.</p>
      )}

      {checklist.length ? (
        <section className="rounded-xl border border-orange-200 bg-orange-50 p-5 shadow-sm">
          <h3 className="font-semibold text-orange-950">확인필요 체크리스트</h3>
          <p className="mt-1 text-sm text-orange-900">건축물대장만으로 단정할 수 없는 공고 조건입니다. 현장에서 확인하세요.</p>
          <ul className="mt-3 space-y-2">
            {checklist.map((item) => (
              <li key={item} className="flex items-start gap-2 text-sm text-orange-950">
                <input type="checkbox" className="mt-0.5 rounded border-orange-300" id={`need-${item}`} />
                <label htmlFor={`need-${item}`}>{item}</label>
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </div>
  );
}

function Field({
  label,
  id,
  value,
  onChange,
  placeholder,
  type = "text",
}: {
  label: string;
  id: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  type?: string;
}) {
  return (
    <div>
      <label className="text-sm font-medium" htmlFor={id}>
        {label}
      </label>
      <input
        id={id}
        type={type}
        className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none ring-gov-600 focus:ring-2"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
      />
    </div>
  );
}
