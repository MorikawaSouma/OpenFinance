"use client";

import { create } from "zustand";
import { createJSONStorage, persist } from "zustand/middleware";

function normalizeNullableString(value: unknown): string | null {
  const next = String(value ?? "").trim();
  return next.length > 0 ? next : null;
}

type ResearchContextStoreState = {
  lastSessionId: string | null;
  lastTraceId: string | null;
  lastPlanId: string | null;
  restoredSessionId: string | null;
  restoredTraceId: string | null;
  lastRestoredAt: string | null;
  setLastSessionId: (sessionId: string | null) => void;
  setLastTraceId: (traceId: string | null) => void;
  setLastPlanId: (planId: string | null) => void;
  setRestoreContext: (payload: {
    sessionId?: string | null;
    traceId?: string | null;
    restoredAt?: string | null;
  }) => void;
  clearRestoreContext: () => void;
  clearResearchContext: () => void;
};

const initialState = {
  lastSessionId: null,
  lastTraceId: null,
  lastPlanId: null,
  restoredSessionId: null,
  restoredTraceId: null,
  lastRestoredAt: null,
} satisfies Pick<
  ResearchContextStoreState,
  "lastSessionId" | "lastTraceId" | "lastPlanId" | "restoredSessionId" | "restoredTraceId" | "lastRestoredAt"
>;

export const useResearchContextStore = create<ResearchContextStoreState>()(
  persist(
    (set) => ({
      ...initialState,

      setLastSessionId: (sessionId) => {
        set({ lastSessionId: normalizeNullableString(sessionId) });
      },

      setLastTraceId: (traceId) => {
        set({ lastTraceId: normalizeNullableString(traceId) });
      },

      setLastPlanId: (planId) => {
        set({ lastPlanId: normalizeNullableString(planId) });
      },

      setRestoreContext: (payload) => {
        set({
          lastSessionId: normalizeNullableString(payload.sessionId),
          lastTraceId: normalizeNullableString(payload.traceId),
          restoredSessionId: normalizeNullableString(payload.sessionId),
          restoredTraceId: normalizeNullableString(payload.traceId),
          lastRestoredAt: normalizeNullableString(payload.restoredAt) ?? new Date().toISOString(),
        });
      },

      clearRestoreContext: () => {
        set({
          restoredSessionId: null,
          restoredTraceId: null,
          lastRestoredAt: null,
        });
      },

      clearResearchContext: () => {
        set(initialState);
      },
    }),
    {
      name: "research_context_v1",
      version: 1,
      storage: createJSONStorage(() => localStorage),
      partialize: (state) => ({
        lastSessionId: state.lastSessionId,
        lastTraceId: state.lastTraceId,
        lastPlanId: state.lastPlanId,
        restoredSessionId: state.restoredSessionId,
        restoredTraceId: state.restoredTraceId,
        lastRestoredAt: state.lastRestoredAt,
      }),
      migrate: (persisted) => {
        if (!persisted || typeof persisted !== "object") return initialState;
        const record = persisted as Record<string, unknown>;
        return {
          lastSessionId: normalizeNullableString(record.lastSessionId),
          lastTraceId: normalizeNullableString(record.lastTraceId),
          lastPlanId: normalizeNullableString(record.lastPlanId),
          restoredSessionId: normalizeNullableString(record.restoredSessionId),
          restoredTraceId: normalizeNullableString(record.restoredTraceId),
          lastRestoredAt: normalizeNullableString(record.lastRestoredAt),
        };
      },
    }
  )
);
