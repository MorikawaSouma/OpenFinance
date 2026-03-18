"use client";

import type { ReactNode } from "react";

import { CatalogSummaryProvider } from "@/components/providers/catalog-summary-provider";
import { RealtimeCoordinatorProvider } from "@/components/providers/realtime-coordinator-provider";
import { ResearchContextProvider } from "@/components/providers/research-context-provider";
import { RiskApprovalProvider } from "@/components/providers/risk-approval-provider";
import { TaskRealtimeProvider } from "@/components/providers/task-realtime-provider";
import { WorkbenchProvider } from "@/components/providers/workbench-provider";
import { WorkbenchShellProvider } from "@/components/providers/workbench-shell-provider";

export function WorkbenchRootProvider({ children }: { children: ReactNode }) {
  return (
    <WorkbenchShellProvider>
      <ResearchContextProvider>
        <TaskRealtimeProvider>
          <RiskApprovalProvider>
            <CatalogSummaryProvider>
              <RealtimeCoordinatorProvider>
                {/* Group 1 keeps the legacy provider as the live runtime owner while new infrastructure is mounted around it. */}
                <WorkbenchProvider>{children}</WorkbenchProvider>
              </RealtimeCoordinatorProvider>
            </CatalogSummaryProvider>
          </RiskApprovalProvider>
        </TaskRealtimeProvider>
      </ResearchContextProvider>
    </WorkbenchShellProvider>
  );
}
