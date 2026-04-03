"use client";

import { useCallback, useMemo, type ReactNode } from "react";

import { useWorkbenchShellActions } from "@/components/providers/workbench-shell-provider";
import { api } from "@/lib/api";
import { useResearchContextStore } from "@/lib/research-context-store";
import type { RestoreBundle } from "@/lib/types";

export type ResearchSessionContinuitySource =
  | "chat.bootstrap_resolved"
  | "chat.user_select"
  | "chat.send_response"
  | "chat.reconcile_fallback";

export function ResearchContextProvider({ children }: { children: ReactNode }) {
  // Research context now carries both durable fallback IDs and one-shot restore payloads for route-local consumers.
  return <>{children}</>;
}

function normalizeNullableString(value: string | null | undefined): string | null {
  const next = String(value ?? "").trim();
  return next.length > 0 ? next : null;
}

function isUserSessionScope(sessionId: string | null) {
  const normalized = String(sessionId ?? "").trim().toLowerCase();
  if (!normalized) return false;
  return !["workbench", "pipeline", "sse", "global"].includes(normalized);
}

export function useResearchContextState() {
  const lastSessionId = useResearchContextStore((state) => state.lastSessionId);
  const lastTraceId = useResearchContextStore((state) => state.lastTraceId);
  const lastPlanId = useResearchContextStore((state) => state.lastPlanId);
  const restoredSessionId = useResearchContextStore((state) => state.restoredSessionId);
  const restoredTraceId = useResearchContextStore((state) => state.restoredTraceId);
  const lastRestoredAt = useResearchContextStore((state) => state.lastRestoredAt);

  return useMemo(
    () => ({
      lastSessionId,
      lastTraceId,
      lastPlanId,
      restoredSessionId,
      restoredTraceId,
      lastRestoredAt,
    }),
    [lastPlanId, lastRestoredAt, lastSessionId, lastTraceId, restoredSessionId, restoredTraceId]
  );
}

export function useResearchContextActions() {
  const setLastTraceId = useResearchContextStore((state) => state.setLastTraceId);
  const setLastPlanId = useResearchContextStore((state) => state.setLastPlanId);
  const setRestoreContext = useResearchContextStore((state) => state.setRestoreContext);
  const clearRestoreContext = useResearchContextStore((state) => state.clearRestoreContext);
  const clearResearchContext = useResearchContextStore((state) => state.clearResearchContext);

  return useMemo(
    () => ({
      setLastTraceId,
      setLastPlanId,
      setRestoreContext,
      clearRestoreContext,
      clearResearchContext,
    }),
    [clearResearchContext, clearRestoreContext, setLastPlanId, setLastTraceId, setRestoreContext]
  );
}

export function useResearchSessionContinuityActions() {
  const setLastSessionId = useResearchContextStore((state) => state.setLastSessionId);

  const commitDefaultSessionScope = useCallback(
    (sessionId: string | null, _source: ResearchSessionContinuitySource) => {
      const normalized = normalizeNullableString(sessionId);
      if (!isUserSessionScope(normalized)) {
        return;
      }
      if (useResearchContextStore.getState().lastSessionId === normalized) {
        return;
      }
      setLastSessionId(normalized);
    },
    [setLastSessionId]
  );

  return useMemo(
    () => ({
      commitDefaultSessionScope,
    }),
    [commitDefaultSessionScope]
  );
}

export function useResearchRestoreActions() {
  const setRestoreContext = useResearchContextStore((state) => state.setRestoreContext);
  const { pushToast } = useWorkbenchShellActions();

  const restoreTraceToResearchContext = useCallback(
    async (
      traceId: string,
      options?: {
        sessionIdHint?: string | null;
        showToast?: boolean;
      }
    ): Promise<RestoreBundle> => {
      const normalizedTraceId = String(traceId ?? "").trim();
      const sessionIdHint = normalizeNullableString(options?.sessionIdHint);
      const bundle = await api.restoreTrace(normalizedTraceId, sessionIdHint ?? undefined);
      const restoredSessionId = normalizeNullableString(bundle.session_state?.session_id);

      if (restoredSessionId) {
        setRestoreContext({
          sessionId: restoredSessionId,
          traceId: normalizedTraceId,
          restoredAt: new Date().toISOString(),
        });
      }

      if (options?.showToast !== false) {
        pushToast("Context restored", bundle.summary, bundle.partial_restore ? "default" : "success");
      }

      return bundle;
    },
    [pushToast, setRestoreContext]
  );

  return useMemo(
    () => ({
      restoreTraceToResearchContext,
    }),
    [restoreTraceToResearchContext]
  );
}
