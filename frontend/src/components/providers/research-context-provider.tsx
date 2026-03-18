"use client";

import type { ReactNode } from "react";

import { useResearchContextStore } from "@/lib/research-context-store";

export function ResearchContextProvider({ children }: { children: ReactNode }) {
  // Research context now carries both durable fallback IDs and one-shot restore payloads for route-local consumers.
  return <>{children}</>;
}

export function useResearchContextState() {
  return useResearchContextStore((state) => ({
    lastSessionId: state.lastSessionId,
    lastTraceId: state.lastTraceId,
    lastPlanId: state.lastPlanId,
    restoredSessionId: state.restoredSessionId,
    restoredTraceId: state.restoredTraceId,
    lastRestoredAt: state.lastRestoredAt,
  }));
}

export function useResearchContextActions() {
  return useResearchContextStore((state) => ({
    setLastSessionId: state.setLastSessionId,
    setLastTraceId: state.setLastTraceId,
    setLastPlanId: state.setLastPlanId,
    setRestoreContext: state.setRestoreContext,
    clearRestoreContext: state.clearRestoreContext,
    clearResearchContext: state.clearResearchContext,
  }));
}
