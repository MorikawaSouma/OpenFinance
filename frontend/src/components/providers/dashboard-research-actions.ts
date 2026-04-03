"use client";

import { useCallback, useMemo } from "react";

import { useCatalogSummaryActions, useCatalogSummaryState } from "@/components/providers/catalog-summary-provider";
import { useTaskRealtimeActions } from "@/components/providers/task-realtime-provider";
import { useWorkbenchShellActions } from "@/components/providers/workbench-shell-provider";
import { api } from "@/lib/api";
import { messages } from "@/lib/messages";
import { useTaskStore } from "@/lib/task-store";
import type { TaskRecord } from "@/lib/types";

const TASK_POLL_INTERVAL_MS = 350;

type DashboardResearchActions = {
  generateDatasetTask: () => Promise<TaskRecord | null>;
  runBacktestTask: () => Promise<TaskRecord | null>;
};

function sleep(ms: number) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function readTaskSessionId(task: TaskRecord): string {
  const meta = task.meta;
  return meta && typeof meta === "object" && !Array.isArray(meta)
    ? String((meta as Record<string, unknown>).session_id ?? "").trim()
    : "";
}

export function useDashboardResearchActions(): DashboardResearchActions {
  const { datasets } = useCatalogSummaryState();
  const { refreshDatasets, refreshRuns } = useCatalogSummaryActions();
  const { ensureTaskHydrated } = useTaskRealtimeActions();
  const { pushToast } = useWorkbenchShellActions();
  const upsertTask = useTaskStore((state) => state.upsertTask);
  const addActiveTask = useTaskStore((state) => state.addActiveTask);

  const waitForTaskTerminal = useCallback(
    async (taskId: string): Promise<TaskRecord> => {
      while (true) {
        const row = await ensureTaskHydrated(taskId);
        if (!row) {
          throw new Error(`Task ${taskId} not found`);
        }
        const status = String(row.status ?? "").toLowerCase();
        if (status === "done" || status === "failed" || status === "error" || status === "canceled") {
          return row;
        }
        await sleep(TASK_POLL_INTERVAL_MS);
      }
    },
    [ensureTaskHydrated]
  );

  const runSeededTask = useCallback(
    async (options: {
      createTask: () => Promise<TaskRecord>;
      createdTitle: string;
      createdDescription: string;
      successTitle: string;
      failureTitle: string;
      afterTerminal: () => Promise<void>;
    }) => {
      try {
        const task = await options.createTask();
        upsertTask(task);
        const sessionId = readTaskSessionId(task);
        if (sessionId) {
          addActiveTask(sessionId, task.task_id);
        }
        pushToast(options.createdTitle, options.createdDescription);
        await waitForTaskTerminal(task.task_id);
        await options.afterTerminal();
        pushToast(options.successTitle, undefined, "success");
        return task;
      } catch (err) {
        pushToast(
          options.failureTitle,
          err instanceof Error ? err.message : messages.toast.unknownError,
          "error"
        );
        return null;
      }
    },
    [addActiveTask, pushToast, upsertTask, waitForTaskTerminal]
  );

  const generateDatasetTask = useCallback(
    async () =>
      runSeededTask({
        createTask: () =>
          api.generateDataset({
            dataset_id: "frontend_dataset",
            market: "US",
            symbol: "AAPL",
            start: "2024-01-01",
            end: "2024-03-31",
            seed: 42,
            base_price: 100,
          }),
        createdTitle: "Task created",
        createdDescription: "Generating dataset...",
        successTitle: "Dataset ready",
        failureTitle: "Dataset generation failed",
        afterTerminal: refreshDatasets,
      }),
    [refreshDatasets, runSeededTask]
  );

  const runBacktestTask = useCallback(
    async () =>
      runSeededTask({
        createTask: () =>
          api.runBacktest({
            dataset_version: datasets[0]?.dataset_version ?? null,
            strategy_id: "frontend_strategy",
            strategy_version: "1.0.0",
            market: "US",
            start: "2024-01-01",
            end: "2024-03-31",
          }),
        createdTitle: "Task created",
        createdDescription: "Running backtest...",
        successTitle: "Backtest completed",
        failureTitle: "Backtest failed",
        afterTerminal: refreshRuns,
      }),
    [datasets, refreshRuns, runSeededTask]
  );

  return useMemo(
    () => ({
      generateDatasetTask,
      runBacktestTask,
    }),
    [generateDatasetTask, runBacktestTask]
  );
}
