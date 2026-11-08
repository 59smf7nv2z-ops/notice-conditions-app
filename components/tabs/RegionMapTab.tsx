"use client";

import { useMemo } from "react";
import { useDashboard } from "@/components/DashboardProvider";
import { KOREA_SIDO } from "@/lib/korea-sido";
import { collectMapPins, noticesOfBatches, sidoIdsWithNotices, type MapPin } from "@/lib/map-model";
import sampleExtract from "@/lib/sample-extract.json";
import type { Extracted, Verdict } from "@/lib/types";

const LNG0 = 124.6;
const LNG1 = 131.6;
const LAT0 = 32.95;
const LAT1 = 38.85;
const W = 720;
const H = 780;

function xy(lat: number, lng: number): { x: number; y: number } {
  return {
    x: ((lng - LNG0) / (LNG1 - LNG0)) * W,
    y: ((LAT1 - lat) / (LAT1 - LAT0)) * H,
  };
}

const PIN_META: Record<Verdict, { label: string }> = {
  해당: { label: "해당" },
  비해당: { label: "비해당" },
  확인필요: { label: "확인필요" },
};

function pinSpread(v: Verdict): { dx: number; dy: number } {
  if (v === "해당") return { dx: -16, dy: -18 };
  if (v === "비해당") return { dx: 18, dy: -14 };
  return { dx: 2, dy: 20 };
}

function RegionShape({ region, active }: { region: (typeof KOREA_SIDO)[number]; active: boolean }) {
  const label = xy(region.center[0], region.center[1]);
  const pts = region.ring.map(([lat, lng]) => {
    const p = xy(lat, lng);
    return `${p.x},${p.y}`;
  });
  return (
    <g>
      <polygon
        points={pts.join(" ")}
        fill={active ? "#2563eb" : "#e5e7eb"}
        stroke={active ? "#1e3a8a" : "#94a3b8"}
        strokeWidth={active ? 2.5 : 1}
      >
        <title>
          {region.name}
          {active ? " · 공고 있음" : " · 공고 없음"}
        </title>
      </polygon>
      <text
        x={label.x}
        y={label.y}
        textAnchor="middle"
        fill={active ? "#f8fafc" : "#475569"}
        fontSize={11}
        fontWeight={active ? 700 : 500}
      >
        {region.name.replace("특별자치", "").replace("광역시", "").replace("특별시", "").replace("도", "")}
      </text>
    </g>
  );
}

function PinMark({ pin }: { pin: MapPin }) {
  const p = xy(pin.lat, pin.lng);
  const o = pinSpread(pin.overall);
  const x = p.x + o.dx;
  const y = p.y + o.dy;
  const title = `${pin.address} · ${PIN_META[pin.overall].label}${pin.sample ? " · 샘플" : ""}`;
  if (pin.overall === "비해당") {
    return (
      <g transform={`translate(${x},${y})`} role="img" aria-label={title}>
        <title>{title}</title>
        <rect x={-8} y={-8} width={16} height={16} fill="#e11d48" stroke="#fff" strokeWidth={2} />
      </g>
    );
  }
  if (pin.overall === "확인필요") {
    return (
      <g transform={`translate(${x},${y}) rotate(45)`} role="img" aria-label={title}>
        <title>{title}</title>
        <rect x={-7} y={-7} width={14} height={14} fill="#ea580c" stroke="#fff" strokeWidth={2} />
      </g>
    );
  }
  return (
    <g transform={`translate(${x},${y})`} role="img" aria-label={title}>
      <title>{title}</title>
      <circle r={9} fill="#059669" stroke="#fff" strokeWidth={2} />
    </g>
  );
}

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
          공고문이 등록된 시·도는 색이 들어가고, 없는 곳은 회색입니다. 건물 주소 핀은 1차 판정에 따라 모양이 달라집니다.
        </p>
      </section>

      <div className="flex flex-wrap gap-3 text-xs text-slate-700">
        <span className="inline-flex items-center gap-1.5">
          <span className="h-3 w-5 rounded-sm bg-gov-600" /> 공고 있는 지역
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="h-3 w-5 rounded-sm bg-slate-200 ring-1 ring-slate-300" /> 공고 없는 지역
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="h-3.5 w-3.5 rounded-full bg-emerald-600 ring-2 ring-white" /> 해당
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="h-3.5 w-3.5 bg-rose-600 ring-2 ring-white" /> 비해당
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="h-3.5 w-3.5 rotate-45 bg-orange-600 ring-2 ring-white" /> 확인필요
        </span>
      </div>

      <p className="text-xs text-slate-500">
        {usedSamples ? "판정이 모자라면 대전 중구 샘플 핀을 함께 표시합니다." : "추출·대조 결과를 지도에 반영했습니다."}
      </p>
      <div className="flex flex-wrap gap-1.5">
        {KOREA_SIDO.map((r) => (
          <span
            key={r.id}
            className={`rounded-full px-2 py-0.5 text-[11px] font-medium ring-1 ${
              coloredIds.includes(r.id)
                ? "bg-blue-700 text-white ring-blue-800"
                : "bg-slate-100 text-slate-500 ring-slate-200"
            }`}
          >
            {r.name.replace("특별자치", "").replace("광역시", "").replace("특별시", "")}
          </span>
        ))}
      </div>

      <div className="overflow-hidden rounded-xl border border-slate-200 bg-white p-3 shadow-sm">
        <svg
          viewBox={`0 0 ${W} ${H}`}
          className="mx-auto h-auto w-full max-h-[36rem]"
          role="img"
          aria-label="시·도별 공고 현황과 건물 1차 판정 핀"
        >
          <rect width={W} height={H} fill="#f8fafc" />
          {KOREA_SIDO.filter((r) => !coloredIds.includes(r.id)).map((region) => (
            <RegionShape key={region.id} region={region} active={false} />
          ))}
          {KOREA_SIDO.filter((r) => coloredIds.includes(r.id)).map((region) => (
            <RegionShape key={region.id} region={region} active />
          ))}
          {pins.map((pin) => (
            <PinMark key={pin.id} pin={pin} />
          ))}
        </svg>
      </div>
    </div>
  );
}
