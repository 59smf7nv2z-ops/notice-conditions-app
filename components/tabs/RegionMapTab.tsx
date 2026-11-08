"use client";

import dynamic from "next/dynamic";
import { FormEvent, useMemo, useState } from "react";
import { useDashboard } from "@/components/DashboardProvider";
import { KOREA_SIDO } from "@/lib/korea-sido";
import { collectMapPins, noticesOfBatches, sidoIdsWithNotices } from "@/lib/map-model";
import { searchMapAddress, type SearchHit } from "@/lib/map-search";
import sampleExtract from "@/lib/sample-extract.json";
import type { Extracted, Verdict } from "@/lib/types";

const LeafletKoreaMap = dynamic(
  () => import("./LeafletKoreaMap").then((m) => m.LeafletKoreaMap),
  {
    ssr: false,
    loading: () => (
      <div className="flex h-[36rem] items-center justify-center bg-slate-100 text-sm text-slate-500">
        지도를 불러오는 중…
      </div>
    ),
  },
);

const HINTS = [
  "대전광역시 중구 은행동 12-3",
  "대전광역시 중구 둔산동 88 공장",
  "서울특별시 종로구 청운동 1",
];

function VerdictBadge({ v }: { v: Verdict }) {
  const cls =
    v === "해당"
      ? "bg-emerald-100 text-emerald-900 ring-emerald-300"
      : v === "비해당"
        ? "bg-rose-100 text-rose-900 ring-rose-300"
        : "bg-orange-100 text-orange-950 ring-orange-300";
  const text = v === "해당" ? "해당(적합)" : v === "비해당" ? "비해당(불적합)" : "확인필요(수동검토)";
  return <span className={`inline-flex rounded-full px-3 py-1 text-sm font-bold ring-1 ${cls}`}>{text}</span>;
}

export function RegionMapTab() {
  const { batches, buildings, liveMatch, notices } = useDashboard();
  const [query, setQuery] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [hit, setHit] = useState<SearchHit | null>(null);

  const allNotices = useMemo(() => {
    const fromBatches = noticesOfBatches(batches);
    return fromBatches.length ? fromBatches : notices.length ? notices : [sampleExtract as Extracted];
  }, [batches, notices]);

  const coloredIds = useMemo(() => {
    const ids = sidoIdsWithNotices(allNotices);
    if (!ids.size) ids.add("daejeon");
    return [...ids];
  }, [allNotices]);

  const { pins, usedSamples } = useMemo(
    () => collectMapPins(buildings, liveMatch, allNotices),
    [buildings, liveMatch, allNotices],
  );

  async function onSearch(e?: FormEvent, preset?: string) {
    e?.preventDefault();
    const q = (preset ?? query).trim();
    if (preset) setQuery(preset);
    setBusy(true);
    setError(null);
    const result = await searchMapAddress(q, pins, allNotices);
    setBusy(false);
    if ("error" in result) {
      setHit(null);
      setError(result.error);
      return;
    }
    setHit(result);
  }

  return (
    <div className="space-y-4">
      <section>
        <h2 className="text-lg font-semibold text-gov-900">지역별 노후건축물 현황 지도</h2>
        <p className="mt-1 text-sm text-slate-600">
          주소를 검색하면 그 위치로 지도를 옮깁니다. 해당 지역에 등록된 공고가 있을 때만 1차 판정을 하고, 없으면 판정하지 않습니다.
        </p>
      </section>

      <form className="flex flex-col gap-2 sm:flex-row sm:items-center" onSubmit={(e) => void onSearch(e)}>
        <label htmlFor="map-address" className="sr-only">
          건물 주소
        </label>
        <input
          id="map-address"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="예: 대전광역시 중구 은행동 12-3"
          className="min-w-0 flex-1 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-gov-900 shadow-sm outline-none ring-gov-600 focus:ring-2"
        />
        <button
          type="submit"
          disabled={busy}
          className="rounded-lg bg-gov-800 px-4 py-2 text-sm font-semibold text-white hover:bg-gov-700 disabled:opacity-60"
        >
          {busy ? "찾는 중…" : "주소 검색"}
        </button>
      </form>
      <div className="flex flex-wrap gap-2">
        {HINTS.map((h) => (
          <button
            key={h}
            type="button"
            className="rounded-full bg-slate-100 px-2.5 py-1 text-xs text-slate-700 ring-1 ring-slate-200 hover:bg-slate-200"
            onClick={() => void onSearch(undefined, h)}
          >
            {h}
          </button>
        ))}
      </div>
      {error ? <p className="text-sm text-rose-700">{error}</p> : null}
      {hit?.kind === "no-notice" ? (
        <div className="rounded-lg border border-slate-200 bg-slate-50 px-4 py-3 shadow-sm">
          <p className="text-xs font-medium text-slate-500">공고 없음</p>
          <p className="mt-1 text-sm font-semibold text-gov-900">{hit.focus.address}</p>
          <p className="mt-2 text-sm text-slate-700">
            {hit.regionName}에 등록된 공고가 없어 다른 지역 공고로 판정하지 않습니다.
          </p>
        </div>
      ) : null}
      {hit?.kind === "verdict" ? (
        <div className="rounded-lg border border-slate-200 bg-white px-4 py-3 shadow-sm">
          <p className="text-xs font-medium text-slate-500">{hit.source === "match" ? "추출·대조 결과" : "모의 대장 판정"}</p>
          <p className="mt-1 text-sm font-semibold text-gov-900">{hit.pin.address}</p>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <VerdictBadge v={hit.pin.overall} />
            <span className="text-xs text-slate-600">{hit.pin.noticeName}</span>
          </div>
        </div>
      ) : null}

      <p className="text-xs text-slate-500">
        {usedSamples ? "판정이 모자라면 대전 중구 샘플 핀을 함께 표시합니다." : "추출·대조 결과를 지도에 반영했습니다."}
      </p>

      <div className="relative min-h-[36rem] overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
        <LeafletKoreaMap coloredIds={coloredIds} pins={pins} focus={hit?.focus ?? null} />
        <div className="pointer-events-none absolute left-3 top-3 z-[500] max-w-[16rem] rounded-lg bg-white/95 p-3 text-xs shadow-md ring-1 ring-slate-200">
          <p className="font-semibold text-gov-900">범례</p>
          <ul className="mt-2 space-y-1.5 text-slate-700">
            <li className="flex items-center gap-2">
              <span className="h-3 w-5 rounded-sm bg-blue-600/80 ring-1 ring-blue-800" /> 공고 있는 지역
            </li>
            <li className="flex items-center gap-2">
              <span className="h-3 w-5 rounded-sm bg-slate-400/50 ring-1 ring-slate-400" /> 공고 없는 지역
            </li>
            <li className="flex items-center gap-2">
              <span className="h-3.5 w-3.5 rounded-full bg-emerald-600 ring-2 ring-white" /> 해당
            </li>
            <li className="flex items-center gap-2">
              <span className="h-3.5 w-3.5 bg-rose-600 ring-2 ring-white" /> 비해당
            </li>
            <li className="flex items-center gap-2">
              <span className="h-3.5 w-3.5 rotate-45 bg-orange-600 ring-2 ring-white" /> 확인필요
            </li>
          </ul>
        </div>
        <div className="pointer-events-none absolute bottom-8 right-3 z-[500] flex flex-wrap justify-end gap-1">
          {KOREA_SIDO.filter((r) => coloredIds.includes(r.id)).map((r) => (
            <span
              key={r.id}
              className="rounded-full bg-blue-700 px-2 py-0.5 text-[11px] font-medium text-white shadow-sm"
            >
              {r.name.replace("특별자치", "").replace("광역시", "").replace("특별시", "")}
            </span>
          ))}
        </div>
      </div>
    </div>
  );
}
