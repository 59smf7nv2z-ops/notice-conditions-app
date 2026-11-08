"use client";

import dynamic from "next/dynamic";
import { useMemo } from "react";
import { useDashboard } from "@/components/DashboardProvider";
import { KOREA_SIDO } from "@/lib/korea-sido";
import { collectMapPins, noticesOfBatches, sidoIdsWithNotices } from "@/lib/map-model";
import sampleExtract from "@/lib/sample-extract.json";
import type { Extracted } from "@/lib/types";

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

export function RegionMapTab() {
  const { batches, buildings, liveMatch, notices } = useDashboard();

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

  return (
    <div className="space-y-4">
      <section>
        <h2 className="text-lg font-semibold text-gov-900">지역별 노후건축물 현황 지도</h2>
        <p className="mt-1 text-sm text-slate-600">
          OpenStreetMap 위에서 공고가 있는 시·도는 파란색, 없는 시·도는 회색입니다. 건물 핀은 1차 판정에 따라 모양이 달라집니다.
          지도를 확대·이동해 주소를 확인할 수 있습니다.
        </p>
      </section>

      <p className="text-xs text-slate-500">
        {usedSamples ? "판정이 모자라면 대전 중구 샘플 핀을 함께 표시합니다." : "추출·대조 결과를 지도에 반영했습니다."}
      </p>

      <div className="relative min-h-[36rem] overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
        <LeafletKoreaMap coloredIds={coloredIds} pins={pins} />
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
