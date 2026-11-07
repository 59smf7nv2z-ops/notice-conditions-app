"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { judgeBuilding } from "@/lib/compare";
import type { BuildingRecord, Extracted, TabId } from "@/lib/types";

const NOTICE_STORE = "notice-extract-results-v1";
const BUILDING_STORE = "notice-buildings-v1";
const LIVE_STORE = "notice-live-match-v1";

type Ctx = {
  tab: TabId;
  setTab: (t: TabId) => void;
  notices: Extracted[];
  setNotices: (n: Extracted[] | ((p: Extracted[]) => Extracted[])) => void;
  selectedNotice: number;
  setSelectedNotice: (i: number) => void;
  notice: Extracted | undefined;
  buildings: BuildingRecord[];
  addBuilding: (input: Omit<BuildingRecord, "id" | "noticeName" | "overall" | "checks">) => void;
  removeBuilding: (id: string) => void;
  clearBuildings: () => void;
  liveMatch: BuildingRecord | null;
  setLiveMatch: (b: BuildingRecord | null) => void;
  resetNonce: number;
  resetForNextMatch: () => void;
  mock: boolean;
  simulated: boolean;
  csrf: string;
  refreshCsrf: () => Promise<string>;
};

const DashboardContext = createContext<Ctx | null>(null);

export function DashboardProvider({ children }: { children: React.ReactNode }) {
  const [tab, setTab] = useState<TabId>("extract");
  const [notices, setNotices] = useState<Extracted[]>([]);
  const [selectedNotice, setSelectedNotice] = useState(0);
  const [buildings, setBuildings] = useState<BuildingRecord[]>([]);
  const [mock, setMock] = useState(true);
  const [simulated, setSimulated] = useState(false);
  const [csrf, setCsrf] = useState("");
  const [liveMatch, setLiveMatch] = useState<BuildingRecord | null>(null);
  const [resetNonce, setResetNonce] = useState(0);

  const refreshCsrf = useCallback(async () => {
    const r = await fetch("/api/status", { cache: "no-store", credentials: "same-origin" });
    if (!r.ok) throw new Error("status");
    const s = (await r.json()) as { mock: boolean; simulated: boolean; csrf?: string };
    setMock(Boolean(s.mock));
    setSimulated(Boolean(s.simulated));
    const token = typeof s.csrf === "string" ? s.csrf : "";
    setCsrf(token);
    return token;
  }, []);

  useEffect(() => {
    try {
      const raw = sessionStorage.getItem(NOTICE_STORE);
      if (raw) setNotices(JSON.parse(raw) as Extracted[]);
      const b = sessionStorage.getItem(BUILDING_STORE);
      if (b) setBuildings(JSON.parse(b) as BuildingRecord[]);
      const live = sessionStorage.getItem(LIVE_STORE);
      if (live) setLiveMatch(JSON.parse(live) as BuildingRecord);
    } catch {
      /* ignore */
    }
    void refreshCsrf().catch(() => undefined);
  }, [refreshCsrf]);

  useEffect(() => {
    try {
      sessionStorage.setItem(NOTICE_STORE, JSON.stringify(notices));
    } catch {
      /* ignore */
    }
  }, [notices]);

  useEffect(() => {
    try {
      sessionStorage.setItem(BUILDING_STORE, JSON.stringify(buildings));
    } catch {
      /* ignore */
    }
  }, [buildings]);

  useEffect(() => {
    try {
      if (liveMatch) sessionStorage.setItem(LIVE_STORE, JSON.stringify(liveMatch));
      else sessionStorage.removeItem(LIVE_STORE);
    } catch {
      /* ignore */
    }
  }, [liveMatch]);

  const notice = notices[selectedNotice];

  const resetForNextMatch = useCallback(() => {
    setBuildings([]);
    setLiveMatch(null);
    setResetNonce((n) => n + 1);
    setTab("compare");
  }, []);

  const addBuilding = useCallback(
    (input: Omit<BuildingRecord, "id" | "noticeName" | "overall" | "checks">) => {
      const current = notices[selectedNotice];
      if (!current) return;
      const judged = judgeBuilding(current, input);
      setBuildings((all) => [
        {
          id: crypto.randomUUID(),
          ...input,
          noticeName: current.공고,
          ...judged,
        },
        ...all,
      ]);
    },
    [notices, selectedNotice],
  );

  const value = useMemo(
    () => ({
      tab,
      setTab,
      notices,
      setNotices,
      selectedNotice,
      setSelectedNotice,
      notice,
      buildings,
      addBuilding,
      removeBuilding: (id: string) => setBuildings((all) => all.filter((b) => b.id !== id)),
      clearBuildings: () => setBuildings([]),
      liveMatch,
      setLiveMatch,
      resetNonce,
      resetForNextMatch,
      mock,
      simulated,
      csrf,
      refreshCsrf,
    }),
    [
      tab,
      notices,
      selectedNotice,
      notice,
      buildings,
      addBuilding,
      liveMatch,
      resetNonce,
      resetForNextMatch,
      mock,
      simulated,
      csrf,
      refreshCsrf,
    ],
  );

  return <DashboardContext.Provider value={value}>{children}</DashboardContext.Provider>;
}

export function useDashboard() {
  const ctx = useContext(DashboardContext);
  if (!ctx) throw new Error("useDashboard");
  return ctx;
}
