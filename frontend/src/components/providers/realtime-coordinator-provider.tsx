"use client";

import { createContext, useContext, useMemo, type ReactNode } from "react";

type RealtimeCoordinatorState = {
  enabled: false;
  ownership: "legacy-workbench-provider";
  connectionState: "legacy-owned";
  note: string;
};

const RealtimeCoordinatorContext = createContext<RealtimeCoordinatorState | null>(null);

export function RealtimeCoordinatorProvider({ children }: { children: ReactNode }) {
  const value = useMemo<RealtimeCoordinatorState>(
    () => ({
      enabled: false,
      ownership: "legacy-workbench-provider",
      connectionState: "legacy-owned",
      note: "Group 1 intentionally leaves SSE ownership on the legacy WorkbenchProvider.",
    }),
    []
  );

  return <RealtimeCoordinatorContext.Provider value={value}>{children}</RealtimeCoordinatorContext.Provider>;
}

export function useRealtimeCoordinator() {
  const ctx = useContext(RealtimeCoordinatorContext);
  if (!ctx) {
    throw new Error("useRealtimeCoordinator must be used within RealtimeCoordinatorProvider");
  }
  return ctx;
}
