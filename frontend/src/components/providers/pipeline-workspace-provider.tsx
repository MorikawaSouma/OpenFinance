"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

import { useResearchContextActions, useResearchContextState } from "@/components/providers/research-context-provider";
import { useTaskRealtimeActions, useTaskRealtimeState } from "@/components/providers/task-realtime-provider";
import { useWorkbenchShellActions } from "@/components/providers/workbench-shell-provider";
import { api } from "@/lib/api";
import { isTaskTerminal, useTaskStore } from "@/lib/task-store";
import type { PipelineResponse, TaskRecord } from "@/lib/types";

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
  renderingSourceOfTruth: "pipeline-workspace-provider";
  businessPathStatus: "workspace-owned-with-task-derived-pipeline-payload";
  question: string;
  market: string;
  highTurnoverMode: boolean;
  autoAdjustForRules: boolean;
  confirmMigrationRisk: boolean;
  running: boolean;
  sessionTaskScope: string;
  pipelineTaskId: string;
  preflightWarnings: PipelinePreflightWarning[];
  activePipelineTask: TaskRecord | null;
  displayPipeline: PipelineResponse | null;
  pipelineInProgress: boolean;
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
  runPipeline: () => Promise<TaskRecord | null>;
  resetWorkspace: () => void;
};

const DEFAULT_PIPELINE_QUESTION =
  "Why is Nikkei volatility rising recently? Build a low-drawdown, high-Sharpe strategy.";
const PIPELINE_TASK_RECONCILE_INTERVAL_MS = 1200;

const PipelineWorkspaceStateContext = createContext<PipelineWorkspaceState | null>(null);
const PipelineWorkspaceActionsContext = createContext<PipelineWorkspaceActions | null>(null);

function toObject(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : {};
}

function resolvePipelineSessionScope(lastSessionId: string | null | undefined): string {
  const sessionId = String(lastSessionId ?? "").trim();
  return sessionId || "pipeline";
}

function isPipelineTaskForScope(task: TaskRecord, sessionTaskScope: string): boolean {
  if (String(task.task_type) !== "pipeline_run") return false;
  const meta = toObject(task.meta);
  const taskSessionId = String(meta.session_id ?? "").trim();
  return taskSessionId === sessionTaskScope;
}

function extractPipelineResponse(task: TaskRecord | null | undefined): PipelineResponse | null {
  if (!task) return null;
  const result = toObject(task.result);
  const payload = result.pipeline_response;
  return payload && typeof payload === "object" ? (payload as PipelineResponse) : null;
}

function buildPipelineConstraints(highTurnoverMode: boolean): Record<string, unknown> {
  if (!highTurnoverMode) return {};
  return {
    factor_cost_sensitivity_level: "high",
    factor_expected_horizon: "intraday",
    expected_turnover: 0.65,
    expected_turnover_threshold: 0.35,
    auto_round_lot: false,
  };
}

export function PipelineWorkspaceProvider({ children }: { children: ReactNode }) {
  const { lastSessionId } = useResearchContextState();
  const { setLastPlanId, setLastTraceId } = useResearchContextActions();
  const { pushToast } = useWorkbenchShellActions();
  const { tasks } = useTaskRealtimeState();
  const { ensureTaskHydrated } = useTaskRealtimeActions();
  const upsertTask = useTaskStore((state) => state.upsertTask);
  const addActiveTask = useTaskStore((state) => state.addActiveTask);

  const [question, setQuestion] = useState(DEFAULT_PIPELINE_QUESTION);
  const [market, setMarket] = useState("JP");
  const [highTurnoverMode, setHighTurnoverMode] = useState(false);
  const [autoAdjustForRules, setAutoAdjustForRules] = useState(false);
  const [confirmMigrationRisk, setConfirmMigrationRisk] = useState(false);
  const [running, setRunning] = useState(false);
  const [pipelineTaskId, setPipelineTaskId] = useState("");
  const [preflightWarnings, setPreflightWarnings] = useState<PipelinePreflightWarning[]>([]);

  const sessionTaskScope = useMemo(() => resolvePipelineSessionScope(lastSessionId), [lastSessionId]);

  const scopedPipelineTasks = useMemo(
    () => tasks.filter((task) => isPipelineTaskForScope(task, sessionTaskScope)),
    [sessionTaskScope, tasks]
  );

  const activePipelineTask = useMemo(() => {
    const explicitTaskId = String(pipelineTaskId ?? "").trim();
    if (explicitTaskId) {
      const explicitTask = tasks.find((task) => String(task.task_id) === explicitTaskId);
      if (explicitTask) return explicitTask;
    }
    return scopedPipelineTasks[0] ?? null;
  }, [pipelineTaskId, scopedPipelineTasks, tasks]);

  const focusedPipelineTaskId = useMemo(() => {
    const explicitTaskId = String(pipelineTaskId ?? "").trim();
    if (explicitTaskId) return explicitTaskId;
    return String(activePipelineTask?.task_id ?? "").trim();
  }, [activePipelineTask, pipelineTaskId]);

  const displayPipeline = useMemo(() => {
    const focusedPayload = extractPipelineResponse(activePipelineTask);
    if (focusedPayload) return focusedPayload;
    for (const task of scopedPipelineTasks) {
      const payload = extractPipelineResponse(task);
      if (payload) return payload;
    }
    return null;
  }, [activePipelineTask, scopedPipelineTasks]);

  const pipelineInProgress = useMemo(() => {
    if (running) return true;
    if (!activePipelineTask) return false;
    return !isTaskTerminal(String(activePipelineTask.status ?? ""));
  }, [activePipelineTask, running]);

  useEffect(() => {
    const taskId = String(focusedPipelineTaskId ?? "").trim();
    if (!taskId) return;

    let cancelled = false;

    // Keep the focused pipeline task hydrated from the task domain without creating a second long-term task cache.
    const reconcileOnce = async () => {
      try {
        await ensureTaskHydrated(taskId);
      } catch {
        // Keep the seeded task visible; task-domain fallback reconcile owns degraded-connection recovery.
      }
    };

    void reconcileOnce();

    if (activePipelineTask && isTaskTerminal(String(activePipelineTask.status ?? ""))) {
      return () => {
        cancelled = true;
      };
    }

    const timer = setInterval(() => {
      if (cancelled) return;
      void reconcileOnce();
    }, PIPELINE_TASK_RECONCILE_INTERVAL_MS);

    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [activePipelineTask, ensureTaskHydrated, focusedPipelineTaskId]);

  const runPipeline = useCallback(async () => {
    setRunning(true);
    try {
      const constraints = buildPipelineConstraints(highTurnoverMode);
      const planPreview = await api.createPlan({ question, market, constraints });
      setLastPlanId(planPreview.plan_id);
      setLastTraceId(planPreview.trace_id);

      const warnings = (planPreview.preflight_warnings ?? []) as PipelinePreflightWarning[];
      setPreflightWarnings(warnings);

      const hasBlock = warnings.some((row) => row.severity === "block");
      if (hasBlock && !autoAdjustForRules && !confirmMigrationRisk) {
        pushToast("Preflight blocked", "Confirm migration risk or enable auto-adjust before running.", "error");
        return null;
      }

      const task = await api.runPlanSubmit({
        question,
        market,
        plan_id: planPreview.plan_id,
        constraints,
        max_drawdown_target: 0.1,
        run_paper_trade: true,
        experiments: 3,
        migration_preflight_confirmed: confirmMigrationRisk,
        auto_adjust_for_market_rules: autoAdjustForRules,
        session_id: sessionTaskScope,
      });

      upsertTask(task);
      addActiveTask(sessionTaskScope, task.task_id);
      setPipelineTaskId(String(task.task_id));
      void ensureTaskHydrated(task.task_id);
      pushToast("Pipeline task submitted", `Task ${String(task.task_id).slice(0, 8)} is running.`, "success");
      return task;
    } catch (err) {
      pushToast("Pipeline failed", err instanceof Error ? err.message : "Unknown error", "error");
      return null;
    } finally {
      setRunning(false);
    }
  }, [
    addActiveTask,
    autoAdjustForRules,
    confirmMigrationRisk,
    highTurnoverMode,
    market,
    ensureTaskHydrated,
    pushToast,
    question,
    sessionTaskScope,
    setLastPlanId,
    setLastTraceId,
    upsertTask,
  ]);

  const state = useMemo<PipelineWorkspaceState>(
    () => ({
      routeOwnership: "pipeline-workspace-provider",
      renderingSourceOfTruth: "pipeline-workspace-provider",
      businessPathStatus: "workspace-owned-with-task-derived-pipeline-payload",
      question,
      market,
      highTurnoverMode,
      autoAdjustForRules,
      confirmMigrationRisk,
      running,
      sessionTaskScope,
      pipelineTaskId,
      preflightWarnings,
      activePipelineTask,
      displayPipeline,
      pipelineInProgress,
    }),
    [
      activePipelineTask,
      autoAdjustForRules,
      confirmMigrationRisk,
      displayPipeline,
      highTurnoverMode,
      market,
      pipelineInProgress,
      pipelineTaskId,
      preflightWarnings,
      question,
      running,
      sessionTaskScope,
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
      runPipeline,
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
    [runPipeline]
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
  // Transitional metadata only. The old WorkbenchProvider runtime is gone; this placeholder survives
  // only so future cleanup can see that pipeline route cleanup finished while naming cleanup remains deferred.
  return {
    bridgeOwnership: "realtime-coordinator-provider" as const,
    bridgeStatus: "unused-compatibility-placeholder" as const,
  };
}
