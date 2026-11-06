"use client";

import { useState } from "react";
import { useDashboard } from "@/components/DashboardProvider";
import type { Verdict } from "@/lib/types";

const empty = {
  address: "",
  ownerHint: "",
  ageYears: "",
  floors: "",
  floorArea: "",
  use: "",
  structure: "",
};

function Badge({ v }: { v: Verdict }) {
  const cls =
    v === "해당"
      ? "bg-emerald-50 text-emerald-800 ring-emerald-200"
      : v === "비해당"
        ? "bg-rose-50 text-rose-800 ring-rose-200"
        : "bg-amber-50 text-amber-900 ring-amber-200";
  return <span className={`inline-flex rounded-full px-2 py-0.5 text-xs font-semibold ring-1 ${cls}`}>{v}</span>;
}

export function BuildingCompareTab() {
  const { notices, selectedNotice, setSelectedNotice, notice, buildings, addBuilding, removeBuilding, clearBuildings } =
    useDashboard();
  const [form, setForm] = useState(empty);
  const [error, setError] = useState<string | null>(null);

  function onJudge() {
    setError(null);
    if (!notice) {
      setError("먼저 공고문 분석 탭에서 조건을 추출하세요.");
      return;
    }
    if (!form.address.trim()) {
      setError("주소를 입력해 주세요.");
      return;
    }
    addBuilding(form);
    setForm(empty);
  }

  return (
    <div className="space-y-6">
      <section>
        <h2 className="text-lg font-semibold text-gov-900">건물 정보 대조 & 1차 판정</h2>
        <p className="mt-1 text-sm text-slate-600">
          주소와 건축물대장 수치를 넣으면 추출된 공고 조건과 자동 대조합니다. 결과는 해당 / 비해당 / 확인필요입니다.
        </p>
      </section>

      <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
        <label className="text-sm font-medium" htmlFor="notice-select">
          대조할 공고
        </label>
        <select
          id="notice-select"
          className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
          value={selectedNotice}
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
            <option value={0}>추출된 공고 없음</option>
          )}
        </select>

        <div className="mt-4 grid gap-3 sm:grid-cols-2">
          <Field label="대지·건축물 주소" id="address" value={form.address} onChange={(v) => setForm({ ...form, address: v })} placeholder="예: 대전광역시 중구 ○○동 12-3" />
          <Field label="소유자·관리자 (선택)" id="owner" value={form.ownerHint} onChange={(v) => setForm({ ...form, ownerHint: v })} />
          <Field label="경과연수(년)" id="age" value={form.ageYears} onChange={(v) => setForm({ ...form, ageYears: v })} placeholder="예: 32" />
          <Field label="지상 층수" id="floors" value={form.floors} onChange={(v) => setForm({ ...form, floors: v })} placeholder="예: 2" />
          <Field label="연면적(㎡)" id="area" value={form.floorArea} onChange={(v) => setForm({ ...form, floorArea: v })} placeholder="예: 280" />
          <Field label="주용도" id="use" value={form.use} onChange={(v) => setForm({ ...form, use: v })} placeholder="예: 주택" />
          <Field label="구조" id="structure" value={form.structure} onChange={(v) => setForm({ ...form, structure: v })} placeholder="예: 조적조" />
        </div>
        <div className="mt-4 flex flex-wrap gap-2">
          <button type="button" className="rounded-lg bg-gov-700 px-4 py-2 text-sm font-semibold text-white hover:bg-gov-800" onClick={onJudge}>
            1차 판정하기
          </button>
          {buildings.length ? (
            <button type="button" className="text-sm text-gov-700" onClick={clearBuildings}>
              판정 목록 비우기
            </button>
          ) : null}
        </div>
        {error ? (
          <p className="mt-3 text-sm text-red-700" role="alert">
            {error}
          </p>
        ) : null}
      </section>

      {buildings.map((b) => (
        <article key={b.id} className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
          <div className="flex flex-wrap items-start justify-between gap-3 border-b border-slate-100 px-5 py-4">
            <div>
              <p className="font-semibold text-gov-900">{b.address}</p>
              <p className="text-xs text-slate-500">
                {b.noticeName}
                {b.ownerHint ? ` · ${b.ownerHint}` : ""}
              </p>
            </div>
            <div className="flex items-center gap-3">
              <Badge v={b.overall} />
              <button type="button" className="text-sm text-slate-500" onClick={() => removeBuilding(b.id)}>
                삭제
              </button>
            </div>
          </div>
          <div className="overflow-x-auto">
            <table className="min-w-full text-left text-sm">
              <thead className="bg-slate-50 text-xs text-slate-500">
                <tr>
                  <th className="px-5 py-2 font-medium">항목</th>
                  <th className="px-5 py-2 font-medium">공고 조건</th>
                  <th className="px-5 py-2 font-medium">대장 값</th>
                  <th className="px-5 py-2 font-medium">판정</th>
                  <th className="px-5 py-2 font-medium">메모</th>
                </tr>
              </thead>
              <tbody>
                {b.checks.map((c) => (
                  <tr key={c.item} className="border-t border-slate-100 align-top">
                    <td className="px-5 py-2 font-medium">{c.item}</td>
                    <td className="px-5 py-2">{c.condition}</td>
                    <td className="px-5 py-2">{c.building}</td>
                    <td className="px-5 py-2">
                      <Badge v={c.verdict} />
                    </td>
                    <td className="px-5 py-2 text-slate-500">{c.note}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </article>
      ))}
    </div>
  );
}

function Field({
  label,
  id,
  value,
  onChange,
  placeholder,
}: {
  label: string;
  id: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
}) {
  return (
    <div>
      <label className="text-sm font-medium" htmlFor={id}>
        {label}
      </label>
      <input
        id={id}
        className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none ring-gov-600 focus:ring-2"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
      />
    </div>
  );
}
