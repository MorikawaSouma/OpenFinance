"use client";

import { createContext, useContext, useEffect, useMemo, useRef, type ReactNode } from "react";

import { useTaskRealtimeState } from "@/components/providers/task-realtime-provider";
import { api } from "@/lib/api";
import { recordStateUpdate } from "@/lib/debug";
import { useCatalogSummaryStore } from "@/lib/catalog-summary-store";
import { isTaskTerminal } from "@/lib/task-store";
import type { TaskRecord } from "@/lib/types";

type CatalogSummaryActions = {
  refreshDatasets: () => Promise<void>;
  refreshRuns: () => Promise<void>;
  refreshStrategies: () => Promise<void>;
};

const CatalogSummaryActionsContext = createContext<CatalogSummaryActions | null>(null);
const DATASET_SUMMARY_TASK_TYPES = new Set(["dataset.generate"]);
const RUN_SUMMARY_TASK_TYPES = new Set(["backtest.run", "pipeline_run", "multi_market.compare", "robustness.run"]);
let datasetsRefreshInFlight: Promise<void> | null = null;
let runsRefreshInFlight: Promise<void> | null = null;
let strategiesRefreshInFlight: Promise<void> | null = null;

function toObject(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : {};
}

function shouldRefreshDatasetSummaries(task: TaskRecord): boolean {
  const type = String(task.task_type ?? "").trim().toLowerCase();
  if (DATASET_SUMMARY_TASK_TYPES.has(type)) return true;
  const result = toObject(task.result);
  return String(result.dataset_version ?? "").trim().length > 0;
}

function shouldRefreshRunSummaries(task: TaskRecord): boolean {
  const type = String(task.task_type ?? "").trim().toLowerCase();
  if (RUN_SUMMARY_TASK_TYPES.has(type)) return true;
  const result = toObject(task.result);
  const resultRef = toObject(task.result_ref);
  return (
    String(result.run_id ?? "").trim().length > 0 ||
    String(resultRef.run_id ?? "").trim().length > 0 ||
    String(resultRef.report_id ?? "").trim().length > 0
  );
}

function shouldRefreshStrategySummaries(task: TaskRecord): boolean {
  const type = String(task.task_type ?? "").trim().toLowerCase();
  if (RUN_SUMMARY_TASK_TYPES.has(type)) return true;
  const result = toObject(task.result);
  const pipelineResponse = toObject(result.pipeline_response);
  return (
    String(result.strategy_version ?? "").trim().length > 0 ||
    String(pipelineResponse.strategy_version ?? "").trim().length > 0
  );
}

export function CatalogSummaryProvider({ children }: { children: ReactNode }) {
  const markOwnership = useCatalogSummaryStore((state) => state.markOwnership);
  const setDatasets = useCatalogSummaryStore((state) => state.setDatasets);
  const setRuns = useCatalogSummaryStore((state) => state.setRuns);
  const setStrategies = useCatalogSummaryStore((state) => state.setStrategies);
  const lastDatasetsRefreshAt = useCatalogSummaryStore((state) => state.lastDatasetsRefreshAt);
  const lastRunsRefreshAt = useCatalogSummaryStore((state) => state.lastRunsRefreshAt);
  const lastStrategiesRefreshAt = useCatalogSummaryStore((state) => state.lastStrategiesRefreshAt);
  const { tasks } = useTaskRealtimeState();
  const taskStatusRef = useRef<Map<string, string>>(new Map());

  const actions = useMemo<CatalogSummaryActions>(
    () => ({
      refreshDatasets: async () => {
        if (datasetsRefreshInFlight) {
          return datasetsRefreshInFlight;
        }
        const refreshPromise = (async () => {
          const rows = await api.getDatasets();
          setDatasets(rows.slice().reverse());
          recordStateUpdate("datasets");
        })();
        datasetsRefreshInFlight = refreshPromise;
        try {
          await refreshPromise;
        } finally {
          if (datasetsRefreshInFlight === refreshPromise) {
            datasetsRefreshInFlight = null;
          }
        }
      },
      refreshRuns: async () => {
        if (runsRefreshInFlight) {
          return runsRefreshInFlight;
        }
        const refreshPromise = (async () => {
          const rows = await api.getRuns();
          setRuns(rows);
          recordStateUpdate("runs");
        })();
        runsRefreshInFlight = refreshPromise;
        try {
          await refreshPromise;
        } finally {
          if (runsRefreshInFlight === refreshPromise) {
            runsRefreshInFlight = null;
          }
        }
      },
      refreshStrategies: async () => {
        if (strategiesRefreshInFlight) {
          return strategiesRefreshInFlight;
        }
        const refreshPromise = (async () => {
          const rows = await api.getStrategies();
          setStrategies(rows);
          recordStateUpdate("strategies");
        })();
        strategiesRefreshInFlight = refreshPromise;
        try {
          await refreshPromise;
        } finally {
          if (strategiesRefreshInFlight === refreshPromise) {
            strategiesRefreshInFlight = null;
          }
        }
      },
    }),
    [setDatasets, setRuns, setStrategies]
  );

  useEffect(() => {
    markOwnership("catalog-summary-provider");
  }, [markOwnership]);

  useEffect(() => {
    if (lastDatasetsRefreshAt !== null && lastRunsRefreshAt !== null && lastStrategiesRefreshAt !== null) return;
    void (async () => {
      try {
        await Promise.all([
          lastDatasetsRefreshAt === null ? actions.refreshDatasets() : Promise.resolve(),
          lastRunsRefreshAt === null ? actions.refreshRuns() : Promise.resolve(),
          lastStrategiesRefreshAt === null ? actions.refreshStrategies() : Promise.resolve(),
        ]);
      } catch {
        // Keep bootstrap failures silent; pages already expose empty/error-adjacent states.
      }
    })();
  }, [actions, lastDatasetsRefreshAt, lastRunsRefreshAt, lastStrategiesRefreshAt]);

  useEffect(() => {
    const nextStatusMap = new Map<string, string>();
    const previousStatusMap = taskStatusRef.current;

    for (const task of tasks) {
      const taskId = String(task.task_id ?? "").trim();
      if (!taskId) continue;
      const status = String(task.status ?? "").trim().toLowerCase();
      nextStatusMap.set(taskId, status);

      const previousStatus = previousStatusMap.get(taskId);
      if (previousStatus === undefined || previousStatus === status) {
        continue;
      }
      if (!isTaskTerminal(status) || status !== "done") {
        continue;
      }

      if (shouldRefreshDatasetSummaries(task)) {
        void actions.refreshDatasets();
      }
      if (shouldRefreshRunSummaries(task)) {
        void actions.refreshRuns();
      }
      if (shouldRefreshStrategySummaries(task)) {
        void actions.refreshStrategies();
      }
    }

    taskStatusRef.current = nextStatusMap;
  }, [actions, tasks]);

  return <CatalogSummaryActionsContext.Provider value={actions}>{children}</CatalogSummaryActionsContext.Provider>;
}

export function useCatalogSummaryState() {
  const ownership = useCatalogSummaryStore((state) => state.ownership);
  const datasets = useCatalogSummaryStore((state) => state.datasets);
  const runs = useCatalogSummaryStore((state) => state.runs);
  const strategies = useCatalogSummaryStore((state) => state.strategies);
  const lastDatasetsRefreshAt = useCatalogSummaryStore((state) => state.lastDatasetsRefreshAt);
  const lastRunsRefreshAt = useCatalogSummaryStore((state) => state.lastRunsRefreshAt);
  const lastStrategiesRefreshAt = useCatalogSummaryStore((state) => state.lastStrategiesRefreshAt);

  return useMemo(
    () => ({
      ownership,
      datasets,
      runs,
      strategies,
      lastDatasetsRefreshAt,
      lastRunsRefreshAt,
      lastStrategiesRefreshAt,
      hasDatasetsLoaded: lastDatasetsRefreshAt !== null,
      hasRunsLoaded: lastRunsRefreshAt !== null,
      hasStrategiesLoaded: lastStrategiesRefreshAt !== null,
      isDatasetsBootstrapPending: lastDatasetsRefreshAt === null && datasets.length === 0,
      isRunsBootstrapPending: lastRunsRefreshAt === null && runs.length === 0,
      isStrategiesBootstrapPending: lastStrategiesRefreshAt === null && strategies.length === 0,
    }),
    [datasets, lastDatasetsRefreshAt, lastRunsRefreshAt, lastStrategiesRefreshAt, ownership, runs, strategies]
  );
}

export function useCatalogSummaryActions() {
  const ctx = useContext(CatalogSummaryActionsContext);
  if (!ctx) {
    throw new Error("useCatalogSummaryActions must be used within CatalogSummaryProvider");
  }
  return ctx;
}
