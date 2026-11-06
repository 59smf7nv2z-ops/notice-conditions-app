"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { judgeBuilding } from "@/lib/compare";
import type { BuildingRecord, Extracted, TabId } from "@/lib/types";

const NOTICE_STORE = "notice-extract-results-v1";
const BUILDING_STORE = "notice-buildings-v1";

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
  mock: boolean;
  simulated: boolean;
};

const DashboardContext = createContext<Ctx | null>(null);

export function DashboardProvider({ children }: { children: React.ReactNode }) {
  const [tab, setTab] = useState<TabId>("extract");
  const [notices, setNotices] = useState<Extracted[]>([]);
  const [selectedNotice, setSelectedNotice] = useState(0);
  const [buildings, setBuildings] = useState<BuildingRecord[]>([]);
  const [mock, setMock] = useState(true);
  const [simulated, setSimulated] = useState(false);

  useEffect(() => {
    try {
      const raw = sessionStorage.getItem(NOTICE_STORE);
      if (raw) setNotices(JSON.parse(raw) as Extracted[]);
      const b = sessionStorage.getItem(BUILDING_STORE);
      if (b) setBuildings(JSON.parse(b) as BuildingRecord[]);
    } catch {
      /* ignore */
    }
    fetch("/api/status", { cache: "no-store" })
      .then(async (r) => {
        if (!r.ok) throw new Error("status");
        return r.json();
      })
      .then((s: { mock: boolean; simulated: boolean }) => {
        setMock(Boolean(s.mock));
        setSimulated(Boolean(s.simulated));
      })
      .catch(() => undefined);
  }, []);

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

  const notice = notices[selectedNotice];

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
      mock,
      simulated,
    }),
    [tab, notices, selectedNotice, notice, buildings, addBuilding, mock, simulated],
  );

  return <DashboardContext.Provider value={value}>{children}</DashboardContext.Provider>;
}

export function useDashboard() {
  const ctx = useContext(DashboardContext);
  if (!ctx) throw new Error("useDashboard");
  return ctx;
}
