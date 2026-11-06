export function MapPlaceholderTab() {
  return (
    <section className="flex min-h-[28rem] flex-col items-center justify-center rounded-xl border border-dashed border-slate-300 bg-white px-6 py-16 text-center shadow-sm">
      <div className="flex h-16 w-16 items-center justify-center rounded-full bg-gov-50 text-gov-700" aria-hidden>
        <svg viewBox="0 0 48 48" className="h-9 w-9" fill="none" stroke="currentColor" strokeWidth="1.8">
          <path d="M8 18.5 24 10l16 8.5v17L24 44 8 35.5v-17Z" />
          <path d="M24 10v34M16 22.5l8 4.5 8-4.5" />
          <circle cx="24" cy="24" r="3.2" fill="currentColor" stroke="none" />
        </svg>
      </div>
      <p className="mt-5 text-base font-semibold text-gov-900">준비 중</p>
      <p className="mt-2 max-w-md text-sm leading-relaxed text-slate-600">
        지역별 노후건축물 현황 지도 기능은 추후 업데이트 예정입니다.
      </p>
    </section>
  );
}
