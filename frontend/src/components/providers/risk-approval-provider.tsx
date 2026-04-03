"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, type ReactNode } from "react";

import { useWorkbenchShellActions } from "@/components/providers/workbench-shell-provider";
import type { ToastItem } from "@/components/ui/toast";
import { api } from "@/lib/api";
import { recordStateUpdate } from "@/lib/debug";
import { messages } from "@/lib/messages";
import { useRiskApprovalStore } from "@/lib/risk-approval-store";
import { useWorkbenchChatStore } from "@/lib/workbench-chat-store";
import type { ApprovalRequest, RiskStatus, SseEvent } from "@/lib/types";

const RISK_APPROVAL_FALLBACK_POLL_MS = 12_000;
let riskApprovalRealtimeRefreshInFlight: Promise<void> | null = null;

type RiskApprovalActions = {
  refreshRiskSnapshot: () => Promise<void>;
  refreshApprovals: () => Promise<void>;
  setKillSwitch: (enabled: boolean) => Promise<void>;
  setLiveUnlock: (enabled: boolean) => Promise<void>;
  setPaperRunning: (enabled: boolean) => Promise<void>;
  requestApproval: (payload: {
    target: "live_trading" | "paper_trading";
    use_case?: string;
    plan_id?: string;
    evidence_pack_id?: string;
    session_id?: string;
    risk_statement_ack?: boolean;
  }) => Promise<void>;
  approveApproval: (requestId: string) => Promise<void>;
  enableApproval: (requestId: string) => Promise<void>;
  revokeApproval: (requestId: string) => Promise<void>;
};

const RiskApprovalActionsContext = createContext<RiskApprovalActions | null>(null);

export function RiskApprovalProvider({ children }: { children: ReactNode }) {
  const markOwnership = useRiskApprovalStore((state) => state.markOwnership);
  const setRiskSnapshot = useRiskApprovalStore((state) => state.setRiskSnapshot);
  const replaceApprovals = useRiskApprovalStore((state) => state.replaceApprovals);
  const upsertApproval = useRiskApprovalStore((state) => state.upsertApproval);
  const lastRiskRefreshAt = useRiskApprovalStore((state) => state.lastRiskRefreshAt);
  const lastApprovalsRefreshAt = useRiskApprovalStore((state) => state.lastApprovalsRefreshAt);
  const sseConnectionState = useWorkbenchChatStore((state) => state.sseConnectionState);
  const { pushToast } = useWorkbenchShellActions();
  const previousSseConnectionStateRef = useRef<string | null>(null);

  useEffect(() => {
    // Phase-2B-3 keeps risk/approval ownership here and replaces legacy broad realtime refresh
    // with domain-owned bootstrap, reconnect reconcile, and degraded-state fallback polling.
    markOwnership("risk-approval-provider");
  }, [markOwnership]);

  const actions = useMemo<RiskApprovalActions>(
    () => ({
      refreshRiskSnapshot: async () => {
        const status = await api.getRiskStatus();
        setRiskSnapshot(status);
      },
      refreshApprovals: async () => {
        const rows = await api.getApprovals();
        replaceApprovals(rows);
      },
      setKillSwitch: async (enabled) => {
        try {
          const status = await api.setKillSwitch(enabled);
          setRiskSnapshot(status);
          pushToast("Kill switch updated", enabled ? "Kill switch ON" : "Kill switch OFF", "success");
        } catch (err) {
          pushToast(
            "Kill switch update failed",
            err instanceof Error ? err.message : messages.toast.unknownError,
            "error"
          );
        }
      },
      setLiveUnlock: async (enabled) => {
        try {
          const status = await api.setLiveUnlock(enabled);
          setRiskSnapshot(status);
          pushToast(
            "Live lock updated",
            status.live_trading_enabled ? "Live trading is enabled." : "Live trading remains locked.",
            status.live_trading_enabled ? "success" : "default"
          );
        } catch (err) {
          pushToast("Live lock update failed", err instanceof Error ? err.message : messages.toast.unknownError, "error");
        }
      },
      setPaperRunning: async (enabled) => {
        try {
          const status = await api.setPaperRunning(enabled);
          setRiskSnapshot(status);
          pushToast(
            "Paper trading status updated",
            enabled ? "Paper trading started." : "Paper trading stopped.",
            "success"
          );
        } catch (err) {
          pushToast(
            "Paper trading update failed",
            err instanceof Error ? err.message : messages.toast.unknownError,
            "error"
          );
        }
      },
      requestApproval: async (payload) => {
        try {
          const row = await api.requestApproval(payload);
          upsertApproval(row);
          const status = await api.getRiskStatus();
          setRiskSnapshot(status);
          pushToast("Approval request submitted", `${payload.target} status: ${row.status}`, "success");
        } catch (err) {
          pushToast("Approval request failed", err instanceof Error ? err.message : messages.toast.unknownError, "error");
        }
      },
      approveApproval: async (requestId) => {
        await updateApprovalStatus(requestId, api.approveApproval, upsertApproval, setRiskSnapshot, pushToast, "approved");
      },
      enableApproval: async (requestId) => {
        await updateApprovalStatus(requestId, api.enableApproval, upsertApproval, setRiskSnapshot, pushToast, "enabled");
      },
      revokeApproval: async (requestId) => {
        await updateApprovalStatus(requestId, api.revokeApproval, upsertApproval, setRiskSnapshot, pushToast, "revoked");
      },
    }),
    [pushToast, replaceApprovals, setRiskSnapshot, upsertApproval]
  );

  const refreshRiskApprovalRealtime = useRefreshRiskApprovalRealtime();

  useEffect(() => {
    if (lastRiskRefreshAt !== null && lastApprovalsRefreshAt !== null) return;
    void refreshRiskApprovalRealtime();
  }, [lastApprovalsRefreshAt, lastRiskRefreshAt, refreshRiskApprovalRealtime]);

  useEffect(() => {
    const previous = previousSseConnectionStateRef.current;
    previousSseConnectionStateRef.current = sseConnectionState;
    if (sseConnectionState === "open" && previous && previous !== "open") {
      void refreshRiskApprovalRealtime();
    }
  }, [refreshRiskApprovalRealtime, sseConnectionState]);

  useEffect(() => {
    if (sseConnectionState === "open") return;
    const timer = setInterval(() => {
      void refreshRiskApprovalRealtime();
    }, RISK_APPROVAL_FALLBACK_POLL_MS);

    return () => {
      clearInterval(timer);
    };
  }, [refreshRiskApprovalRealtime, sseConnectionState]);

  return <RiskApprovalActionsContext.Provider value={actions}>{children}</RiskApprovalActionsContext.Provider>;
}

export function useRiskApprovalState() {
  const riskSnapshot = useRiskApprovalStore((state) => state.riskSnapshot);
  const approvalOrder = useRiskApprovalStore((state) => state.approvalOrder);
  const approvalsById = useRiskApprovalStore((state) => state.approvalsById);
  const ownership = useRiskApprovalStore((state) => state.ownership);
  const lastRiskRefreshAt = useRiskApprovalStore((state) => state.lastRiskRefreshAt);
  const lastApprovalsRefreshAt = useRiskApprovalStore((state) => state.lastApprovalsRefreshAt);

  return {
    ownership,
    riskSnapshot,
    approvals: approvalOrder.map((requestId) => approvalsById[requestId]).filter(Boolean),
    lastRiskRefreshAt,
    lastApprovalsRefreshAt,
    hasRiskSnapshotLoaded: lastRiskRefreshAt !== null,
    hasApprovalsLoaded: lastApprovalsRefreshAt !== null,
    isRiskBootstrapPending: lastRiskRefreshAt === null && riskSnapshot === null,
    isApprovalsBootstrapPending: lastApprovalsRefreshAt === null && approvalOrder.length === 0,
  };
}

export function useRiskApprovalActions() {
  const ctx = useContext(RiskApprovalActionsContext);
  if (!ctx) {
    throw new Error("useRiskApprovalActions must be used within RiskApprovalProvider");
  }
  return ctx;
}

function useRefreshRiskApprovalRealtime() {
  const setRiskSnapshot = useRiskApprovalStore((state) => state.setRiskSnapshot);
  const replaceApprovals = useRiskApprovalStore((state) => state.replaceApprovals);

  return useCallback(async () => {
    if (riskApprovalRealtimeRefreshInFlight) {
      return riskApprovalRealtimeRefreshInFlight;
    }

    const refreshPromise = (async () => {
      try {
        const [riskRes, approvalsRes] = await Promise.all([api.getRiskStatus(), api.getApprovals()]);
        setRiskSnapshot(riskRes);
        replaceApprovals(approvalsRes);
        recordStateUpdate("risk");
        recordStateUpdate("approvals");
      } catch {
        // Keep realtime refresh failures silent; the event toast should still appear.
      }
    })();

    riskApprovalRealtimeRefreshInFlight = refreshPromise;
    try {
      await refreshPromise;
    } finally {
      if (riskApprovalRealtimeRefreshInFlight === refreshPromise) {
        riskApprovalRealtimeRefreshInFlight = null;
      }
    }
  }, [replaceApprovals, setRiskSnapshot]);
}

export function useRiskApprovalRealtimeHandlers() {
  const refreshRiskApprovalRealtime = useRefreshRiskApprovalRealtime();
  const { pushToast } = useWorkbenchShellActions();

  const handleRiskEvent = useCallback(
    (event: SseEvent) => {
      if (String(event.type ?? "").trim().toLowerCase() !== "risk.event") return;
      void refreshRiskApprovalRealtime();
      const payload = event.payload ?? {};
      const message = String(payload.message ?? payload.event_type ?? "Risk event detected");
      pushToast("Risk event", message, "error");
    },
    [pushToast, refreshRiskApprovalRealtime]
  );

  const handleApprovalStatusChanged = useCallback(
    (event: SseEvent) => {
      if (String(event.type ?? "").trim().toLowerCase() !== "approval.status_changed") return;
      void refreshRiskApprovalRealtime();
      const payload = event.payload ?? {};
      const requestId = String(payload.request_id ?? "");
      const status = String(payload.status ?? "");
      if (requestId && status) {
        pushToast("Approval status changed", `${requestId} -> ${status}`, "default");
      }
    },
    [pushToast, refreshRiskApprovalRealtime]
  );

  return useMemo(
    () => ({
      handleRiskEvent,
      handleApprovalStatusChanged,
    }),
    [handleApprovalStatusChanged, handleRiskEvent]
  );
}

async function updateApprovalStatus(
  requestId: string,
  requestFn: (requestId: string) => Promise<ApprovalRequest>,
  upsertApproval: (row: ApprovalRequest) => void,
  setRiskSnapshot: (snapshot: RiskStatus | null) => void,
  pushToast: (title: string, description?: string, variant?: ToastItem["variant"]) => string,
  statusLabel: string
) {
  try {
    const row = await requestFn(requestId);
    upsertApproval(row);
    const status = await api.getRiskStatus();
    setRiskSnapshot(status);
    pushToast("Approval updated", `${requestId} -> ${statusLabel}`, "success");
  } catch (err) {
    pushToast(
      `${capitalize(statusLabel)} failed`,
      err instanceof Error ? err.message : messages.toast.unknownError,
      "error"
    );
  }
}

function capitalize(value: string) {
  return value ? `${value[0]?.toUpperCase() ?? ""}${value.slice(1)}` : value;
}
