"use client";

import { create } from "zustand";

import type { ApprovalRequest, RiskStatus } from "@/lib/types";

function mergeApprovalOrder(current: string[], incoming: string[]): string[] {
  const order: string[] = [];
  const seen = new Set<string>();
  for (const raw of [...incoming, ...current]) {
    const key = String(raw ?? "").trim();
    if (!key || seen.has(key)) continue;
    seen.add(key);
    order.push(key);
  }
  return order;
}

export type RiskApprovalOwnership = "placeholder" | "legacy-workbench";

type RiskApprovalStoreState = {
  ownership: RiskApprovalOwnership;
  riskSnapshot: RiskStatus | null;
  approvalsById: Record<string, ApprovalRequest>;
  approvalOrder: string[];
  lastRiskRefreshAt: string | null;
  lastApprovalsRefreshAt: string | null;
  markOwnership: (next: RiskApprovalOwnership) => void;
  setRiskSnapshot: (snapshot: RiskStatus | null, refreshedAt?: string | null) => void;
  replaceApprovals: (rows: ApprovalRequest[], refreshedAt?: string | null) => void;
  upsertApproval: (row: ApprovalRequest, refreshedAt?: string | null) => void;
  clearRiskApprovalState: () => void;
};

export const useRiskApprovalStore = create<RiskApprovalStoreState>()((set) => ({
  ownership: "placeholder",
  riskSnapshot: null,
  approvalsById: {},
  approvalOrder: [],
  lastRiskRefreshAt: null,
  lastApprovalsRefreshAt: null,

  markOwnership: (next) => {
    set({ ownership: next });
  },

  setRiskSnapshot: (snapshot, refreshedAt) => {
    set({
      riskSnapshot: snapshot,
      lastRiskRefreshAt: refreshedAt ?? new Date().toISOString(),
    });
  },

  replaceApprovals: (rows, refreshedAt) => {
    const approvalsById: Record<string, ApprovalRequest> = {};
    const order: string[] = [];
    for (const row of rows) {
      const requestId = String(row.request_id ?? "").trim();
      if (!requestId) continue;
      approvalsById[requestId] = row;
      order.push(requestId);
    }
    set({
      approvalsById,
      approvalOrder: order,
      lastApprovalsRefreshAt: refreshedAt ?? new Date().toISOString(),
    });
  },

  upsertApproval: (row, refreshedAt) => {
    const requestId = String(row.request_id ?? "").trim();
    if (!requestId) return;
    set((state) => ({
      approvalsById: {
        ...state.approvalsById,
        [requestId]: row,
      },
      approvalOrder: mergeApprovalOrder(state.approvalOrder, [requestId]),
      lastApprovalsRefreshAt: refreshedAt ?? new Date().toISOString(),
    }));
  },

  clearRiskApprovalState: () => {
    set({
      riskSnapshot: null,
      approvalsById: {},
      approvalOrder: [],
      lastRiskRefreshAt: null,
      lastApprovalsRefreshAt: null,
    });
  },
}));
