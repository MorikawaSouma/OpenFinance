"use client";

import { useEffect, type ReactNode } from "react";

import { CatalogSummaryProvider } from "@/components/providers/catalog-summary-provider";
import { RealtimeCoordinatorProvider } from "@/components/providers/realtime-coordinator-provider";
import { ResearchContextProvider } from "@/components/providers/research-context-provider";
import { RiskApprovalProvider } from "@/components/providers/risk-approval-provider";
import { TaskRealtimeProvider } from "@/components/providers/task-realtime-provider";
import { WorkbenchShellProvider } from "@/components/providers/workbench-shell-provider";
import { installDomMutationGuard } from "@/lib/dom-guard";

export function WorkbenchRootProvider({ children }: { children: ReactNode }) {
  useEffect(() => {
    installDomMutationGuard();
  }, []);

  // Root/global responsibilities now live here: shell wiring, research continuity, domain providers,
  // realtime infrastructure composition, and the DOM mutation guard.
  return (
    <WorkbenchShellProvider>
      <ResearchContextProvider>
        <TaskRealtimeProvider>
          <RiskApprovalProvider>
            <CatalogSummaryProvider>
              <RealtimeCoordinatorProvider>
                {children}
              </RealtimeCoordinatorProvider>
            </CatalogSummaryProvider>
          </RiskApprovalProvider>
        </TaskRealtimeProvider>
      </ResearchContextProvider>
    </WorkbenchShellProvider>
  );
}
