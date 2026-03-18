"use client";

import { createContext, useContext, useEffect, useMemo, type ReactNode } from "react";

import { useWorkbenchShellActions } from "@/components/providers/workbench-shell-provider";
import type { ToastItem } from "@/components/ui/toast";
import { api } from "@/lib/api";
import { messages } from "@/lib/messages";
import { useRiskApprovalStore } from "@/lib/risk-approval-store";
import type { ApprovalRequest, RiskStatus } from "@/lib/types";

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
  const { pushToast } = useWorkbenchShellActions();

  useEffect(() => {
    // Group 2A wires targeted risk/approval actions here, but initial hydrate and SSE freshness still come from the legacy bridge.
    markOwnership("legacy-workbench");
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
  };
}

export function useRiskApprovalActions() {
  const ctx = useContext(RiskApprovalActionsContext);
  if (!ctx) {
    throw new Error("useRiskApprovalActions must be used within RiskApprovalProvider");
  }
  return ctx;
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
