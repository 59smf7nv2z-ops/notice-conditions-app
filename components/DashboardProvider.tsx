"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { makeBatch } from "@/lib/batch";
import { judgeBuilding } from "@/lib/compare";
import type { ExtractBatch, BuildingRecord, Extracted, TabId } from "@/lib/types";

const NOTICE_STORE = "notice-extract-results-v1";
const BATCH_STORE = "notice-extract-batches-v1";
const BUILDING_STORE = "notice-buildings-v1";
const LIVE_STORE = "notice-live-match-v1";

type Ctx = {
  tab: TabId;
  setTab: (t: TabId) => void;
  batches: ExtractBatch[];
  selectedBatch: number;
  setSelectedBatch: (i: number) => void;
  addBatch: (items: Extracted[]) => void;
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
  canLiveExtract: boolean;
  viewer: string;
  csrf: string;
  refreshCsrf: () => Promise<string>;
};

const DashboardContext = createContext<Ctx | null>(null);

function migrateNotices(list: Extracted[]): ExtractBatch[] {
  return list.map((item) => makeBatch([item]));
}

export function DashboardProvider({ children }: { children: React.ReactNode }) {
  const [tab, setTab] = useState<TabId>("extract");
  const [batches, setBatches] = useState<ExtractBatch[]>([]);
  const [selectedBatch, setSelectedBatch] = useState(0);
  const [selectedNotice, setSelectedNotice] = useState(0);
  const [buildings, setBuildings] = useState<BuildingRecord[]>([]);
  const [mock, setMock] = useState(true);
  const [simulated, setSimulated] = useState(false);
  const [canLiveExtract, setCanLiveExtract] = useState(false);
  const [viewer, setViewer] = useState("");
  const [csrf, setCsrf] = useState("");
  const [liveMatch, setLiveMatch] = useState<BuildingRecord | null>(null);
  const [resetNonce, setResetNonce] = useState(0);

  const refreshCsrf = useCallback(async () => {
    const r = await fetch("/api/status", { cache: "no-store", credentials: "same-origin" });
    if (!r.ok) throw new Error("status");
    const s = (await r.json()) as {
      mock: boolean;
      simulated: boolean;
      canLiveExtract?: boolean;
      viewer?: string;
      csrf?: string;
    };
    setMock(Boolean(s.mock));
    setSimulated(Boolean(s.simulated));
    setCanLiveExtract(Boolean(s.canLiveExtract));
    setViewer(typeof s.viewer === "string" ? s.viewer : "");
    const token = typeof s.csrf === "string" ? s.csrf : "";
    setCsrf(token);
    return token;
  }, []);

  useEffect(() => {
    try {
      const storedBatches = sessionStorage.getItem(BATCH_STORE);
      if (storedBatches) {
        const parsed = JSON.parse(storedBatches) as ExtractBatch[];
        if (Array.isArray(parsed) && parsed.length) setBatches(parsed);
      } else {
        const raw = sessionStorage.getItem(NOTICE_STORE);
        if (raw) {
          const list = JSON.parse(raw) as Extracted[];
          if (Array.isArray(list) && list.length) setBatches(migrateNotices(list));
        }
      }
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
      sessionStorage.setItem(BATCH_STORE, JSON.stringify(batches));
      sessionStorage.setItem(NOTICE_STORE, JSON.stringify(batches.flatMap((b) => b.items)));
    } catch {
      /* ignore */
    }
  }, [batches]);

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

  const notices = batches[selectedBatch]?.items ?? [];
  const notice = notices[selectedNotice];

  const addBatch = useCallback((items: Extracted[]) => {
    if (!items.length) return;
    const batch = makeBatch(items);
    setBatches((prev) => {
      setSelectedBatch(prev.length);
      return [...prev, batch];
    });
    setSelectedNotice(0);
  }, []);

  const setNotices = useCallback((n: Extracted[] | ((p: Extracted[]) => Extracted[])) => {
    if (typeof n === "function") {
      setBatches((prev) => {
        const flat = prev.flatMap((b) => b.items);
        const next = n(flat);
        if (!next.length) {
          setSelectedBatch(0);
          setSelectedNotice(0);
          return [];
        }
        return migrateNotices(next);
      });
      return;
    }
    if (!n.length) {
      setBatches([]);
      setSelectedBatch(0);
      setSelectedNotice(0);
      return;
    }
    addBatch(n);
  }, [addBatch]);

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

  const selectBatch = useCallback((i: number) => {
    setSelectedBatch(i);
    setSelectedNotice(0);
  }, []);

  const value = useMemo(
    () => ({
      tab,
      setTab,
      batches,
      selectedBatch,
      setSelectedBatch: selectBatch,
      addBatch,
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
      canLiveExtract,
      viewer,
      csrf,
      refreshCsrf,
    }),
    [
      tab,
      batches,
      selectedBatch,
      selectBatch,
      addBatch,
      notices,
      setNotices,
      selectedNotice,
      notice,
      buildings,
      addBuilding,
      liveMatch,
      resetNonce,
      resetForNextMatch,
      mock,
      simulated,
      canLiveExtract,
      viewer,
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
