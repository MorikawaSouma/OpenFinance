"use client";

import { createContext, useContext, useMemo, useState, type ReactNode } from "react";

import { useWorkbench, useWorkbenchTasks } from "@/components/providers/workbench-provider";

export type PipelinePreflightWarning = {
  market: string;
  severity: string;
  title: string;
  explanation: string;
  suggestion?: string;
  code: string;
  variant_id?: string | null;
};

type PipelineWorkspaceState = {
  routeOwnership: "pipeline-workspace-provider";
  foundationStatus: "page-state-owned";
  question: string;
  market: string;
  highTurnoverMode: boolean;
  autoAdjustForRules: boolean;
  confirmMigrationRisk: boolean;
  running: boolean;
  pipelineTaskId: string;
  preflightWarnings: PipelinePreflightWarning[];
};

type PipelineWorkspaceActions = {
  setQuestion: (next: string) => void;
  setMarket: (next: string) => void;
  setHighTurnoverMode: (next: boolean) => void;
  setAutoAdjustForRules: (next: boolean) => void;
  setConfirmMigrationRisk: (next: boolean) => void;
  setRunning: (next: boolean) => void;
  setPipelineTaskId: (next: string) => void;
  setPreflightWarnings: (next: PipelinePreflightWarning[]) => void;
  resetWorkspace: () => void;
};

const DEFAULT_PIPELINE_QUESTION =
  "Why is Nikkei volatility rising recently? Build a low-drawdown, high-Sharpe strategy.";

const PipelineWorkspaceStateContext = createContext<PipelineWorkspaceState | null>(null);
const PipelineWorkspaceActionsContext = createContext<PipelineWorkspaceActions | null>(null);

export function PipelineWorkspaceProvider({ children }: { children: ReactNode }) {
  const [question, setQuestion] = useState(DEFAULT_PIPELINE_QUESTION);
  const [market, setMarket] = useState("JP");
  const [highTurnoverMode, setHighTurnoverMode] = useState(false);
  const [autoAdjustForRules, setAutoAdjustForRules] = useState(false);
  const [confirmMigrationRisk, setConfirmMigrationRisk] = useState(false);
  const [running, setRunning] = useState(false);
  const [pipelineTaskId, setPipelineTaskId] = useState("");
  const [preflightWarnings, setPreflightWarnings] = useState<PipelinePreflightWarning[]>([]);

  const state = useMemo<PipelineWorkspaceState>(
    () => ({
      routeOwnership: "pipeline-workspace-provider",
      foundationStatus: "page-state-owned",
      question,
      market,
      highTurnoverMode,
      autoAdjustForRules,
      confirmMigrationRisk,
      running,
      pipelineTaskId,
      preflightWarnings,
    }),
    [
      autoAdjustForRules,
      confirmMigrationRisk,
      highTurnoverMode,
      market,
      pipelineTaskId,
      preflightWarnings,
      question,
      running,
    ]
  );

  const actions = useMemo<PipelineWorkspaceActions>(
    () => ({
      setQuestion,
      setMarket,
      setHighTurnoverMode,
      setAutoAdjustForRules,
      setConfirmMigrationRisk,
      setRunning,
      setPipelineTaskId,
      setPreflightWarnings,
      resetWorkspace: () => {
        setQuestion(DEFAULT_PIPELINE_QUESTION);
        setMarket("JP");
        setHighTurnoverMode(false);
        setAutoAdjustForRules(false);
        setConfirmMigrationRisk(false);
        setRunning(false);
        setPipelineTaskId("");
        setPreflightWarnings([]);
      },
    }),
    []
  );

  return (
    <PipelineWorkspaceStateContext.Provider value={state}>
      <PipelineWorkspaceActionsContext.Provider value={actions}>{children}</PipelineWorkspaceActionsContext.Provider>
    </PipelineWorkspaceStateContext.Provider>
  );
}

export function usePipelineWorkspaceState() {
  const ctx = useContext(PipelineWorkspaceStateContext);
  if (!ctx) {
    throw new Error("usePipelineWorkspaceState must be used within PipelineWorkspaceProvider");
  }
  return ctx;
}

export function usePipelineWorkspaceActions() {
  const ctx = useContext(PipelineWorkspaceActionsContext);
  if (!ctx) {
    throw new Error("usePipelineWorkspaceActions must be used within PipelineWorkspaceProvider");
  }
  return ctx;
}

export function usePipelineWorkspaceLegacyBridge() {
  // Explicit transitional bridge: execution, artifact freshness, and task linkage remain legacy-backed after page-state migration.
  const workbench = useWorkbench();
  const workbenchTasks = useWorkbenchTasks();
  const sessionTaskScope = (workbench.activeSessionId || "pipeline").trim();

  return {
    bridgeOwnership: "legacy-workbench-provider" as const,
    bridgeStatus: "required-for-pipeline-data-and-actions" as const,
    mode: workbench.mode,
    latestPipeline: workbench.latestPipeline,
    runPipeline: workbench.runPipeline,
    pushToast: workbench.pushToast,
    activeSessionId: workbench.activeSessionId,
    sessionTaskScope,
    tasks: workbenchTasks.tasks,
    activeTasksCount: workbenchTasks.activeTasksCount,
  };
}
