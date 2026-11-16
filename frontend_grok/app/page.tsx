"use client";

import { DashboardProvider } from "@/components/DashboardProvider";
import { DashboardShell } from "@/components/DashboardShell";

export default function Page() {
  return (
    <DashboardProvider>
      <DashboardShell />
    </DashboardProvider>
  );
}
