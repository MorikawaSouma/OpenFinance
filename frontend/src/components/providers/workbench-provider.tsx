"use client";

import {
  createContext,
  startTransition,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

import { useCatalogSummaryState } from "@/components/providers/catalog-summary-provider";
import { useResearchContextActions } from "@/components/providers/research-context-provider";
import { useRiskApprovalActions, useRiskApprovalState } from "@/components/providers/risk-approval-provider";
import { useTaskRealtimeState } from "@/components/providers/task-realtime-provider";
import { useWorkbenchShellActions, useWorkbenchShellState } from "@/components/providers/workbench-shell-provider";
import type { ToastItem } from "@/components/ui/toast";
import { api } from "@/lib/api";
import { executeChatSend } from "@/lib/chat-runtime";
import { useChatSessionStore } from "@/lib/chat-session-store";
import {
  recordBeforeUnload,
  recordSseClose,
  recordSseError,
  recordSseOpen,
  recordSseReconnect,
  recordStateUpdate,
  recordVisibilityChange,
} from "@/lib/debug";
import { subscribeEvents } from "@/lib/events";
import { useCatalogSummaryStore } from "@/lib/catalog-summary-store";
import { messages } from "@/lib/messages";
import { useRiskApprovalStore } from "@/lib/risk-approval-store";
import { isTaskTerminal, useTaskStore } from "@/lib/task-store";
import { useWorkbenchChatStore } from "@/lib/workbench-chat-store";
import { installDomMutationGuard } from "@/lib/dom-guard";
import type {
  ApprovalRequest,
  ChatResponse,
  DatasetEntry,
  Mode,
  PipelineResponse,
  RestoreBundle,
  RiskStatus,
  RunSummary,
  SseEvent,
  StrategySummary,
  TaskRecord,
} from "@/lib/types";

type WorkbenchContextShape = {
  mode: Mode;
  setMode: (next: Mode) => void;
  loadingCore: boolean;
  refreshingCore: boolean;
  coreError: string | null;
  datasets: DatasetEntry[];
  runs: RunSummary[];
  strategies: StrategySummary[];
  risk: RiskStatus | null;
  approvals: ApprovalRequest[];
  latestDatasetVersion: string | null;
  latestStrategyVersion: string | null;
  latestPipeline: PipelineResponse | null;
  activeSessionId: string | null;
  refreshCore: () => Promise<void>;
  generateDataset: () => Promise<void>;
  runBacktest: () => Promise<void>;
  runPipeline: (
    question: string,
    market?: string,
    options?: {
      planId?: string;
      constraints?: Record<string, unknown>;
      migrationPreflightConfirmed?: boolean;
      autoAdjustForMarketRules?: boolean;
    }
  ) => Promise<TaskRecord>;
  sendChat: (message: string) => Promise<ChatResponse>;
  pushToast: (title: string, description?: string, variant?: ToastItem["variant"]) => void;
  setKillSwitch: (enabled: boolean) => Promise<void>;
  setLiveUnlock: (enabled: boolean) => Promise<void>;
  setPaperRunning: (enabled: boolean) => Promise<void>;
  restoreTraceContext: (traceId: string) => Promise<RestoreBundle>;
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

type WorkbenchChatActionsContextShape = {
  selectSession: (sessionId: string) => Promise<void>;
  syncActiveSession: (sessionId: string | null) => void;
};

const WorkbenchContext = createContext<WorkbenchContextShape | null>(null);
const WorkbenchChatActionsContext = createContext<WorkbenchChatActionsContextShape | null>(null);

function toObject(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : {};
}

function taskTimestamp(task: TaskRecord): number {
  const updated = Date.parse(String(task.updated_at ?? ""));
  if (Number.isFinite(updated)) return updated;
  const created = Date.parse(String(task.created_at ?? ""));
  if (Number.isFinite(created)) return created;
  return 0;
}

function extractPipelineResponse(task: TaskRecord): PipelineResponse | null {
  if (String(task.task_type) !== "pipeline_run") return null;
  if (String(task.status).toLowerCase() !== "done") return null;
  const result = toObject(task.result);
  const payload = toObject(result.pipeline_response);
  if (Object.keys(payload).length === 0) return null;
  return payload as unknown as PipelineResponse;
}

type RefreshOptions = {
  silent?: boolean;
};

export function WorkbenchProvider({ children }: { children: ReactNode }) {
  // Compatibility bridge contract:
  // - shell mode/toasts, catalog summaries, risk snapshot, approvals, and task selectors are read from dedicated domain stores.
  // - global SSE/event handling, latest pipeline, restore/bootstrap behavior, and deprecated compatibility surfaces stay legacy-backed until later groups.
  // - placeholder-only actions remain outside this bridge; this file must not regain primary ownership of the domain stores above.
  const { mode } = useWorkbenchShellState();
  const { setMode, pushToast } = useWorkbenchShellActions();
  const { datasets, runs, strategies } = useCatalogSummaryState();
  const { riskSnapshot: risk, approvals } = useRiskApprovalState();
  const {
    setKillSwitch: setKillSwitchAction,
    setLiveUnlock: setLiveUnlockAction,
    setPaperRunning: setPaperRunningAction,
    requestApproval: requestApprovalAction,
    approveApproval: approveApprovalAction,
    enableApproval: enableApprovalAction,
    revokeApproval: revokeApprovalAction,
  } = useRiskApprovalActions();
  const setCatalogOwnership = useCatalogSummaryStore((state) => state.markOwnership);
  const setCatalogDatasets = useCatalogSummaryStore((state) => state.setDatasets);
  const setCatalogRuns = useCatalogSummaryStore((state) => state.setRuns);
  const setCatalogStrategies = useCatalogSummaryStore((state) => state.setStrategies);
  const setRiskOwnership = useRiskApprovalStore((state) => state.markOwnership);
  const setRiskSnapshot = useRiskApprovalStore((state) => state.setRiskSnapshot);
  const replaceApprovals = useRiskApprovalStore((state) => state.replaceApprovals);
  const upsertApproval = useRiskApprovalStore((state) => state.upsertApproval);
  const { setLastSessionId, setRestoreContext } = useResearchContextActions();
  const [loadingCore, setLoadingCore] = useState(true);
  const [refreshingCore, setRefreshingCore] = useState(false);
  const [coreError, setCoreError] = useState<string | null>(null);
  const [latestPipeline, setLatestPipeline] = useState<PipelineResponse | null>(null);

  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const upsertChatResponse = useChatSessionStore((state) => state.upsertFromResponse);
  const upsertTask = useTaskStore((state) => state.upsertTask);
  const replaceTasks = useTaskStore((state) => state.replaceTasks);
  const addActiveTask = useTaskStore((state) => state.addActiveTask);
  const syncTaskTerminalState = useTaskStore((state) => state.syncTaskTerminalState);

  const eventBufferRef = useRef<SseEvent[]>([]);
  const seenEventOrderRef = useRef<string[]>([]);
  const seenEventIdsRef = useRef<Set<string>>(new Set());
  const eventFlushTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const refreshTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const prependEvents = useWorkbenchChatStore((state) => state.prependEvents);
  const setSseConnectionState = useWorkbenchChatStore((state) => state.setSseConnectionState);

  const syncActiveSession = useCallback(
    (sessionId: string | null) => {
      const nextSessionId = String(sessionId ?? "").trim();
      setActiveSessionId(nextSessionId || null);
      if (nextSessionId) {
        setLastSessionId(nextSessionId);
      }
      recordStateUpdate("activeSessionId");
    },
    [setLastSessionId]
  );

  const syncLatestPipeline = useCallback((task: TaskRecord) => {
    const payload = extractPipelineResponse(task);
    if (!payload) return;
    startTransition(() => {
      setLatestPipeline(payload);
    });
    recordStateUpdate("latestPipeline");
  }, []);

  const syncLatestPipelineFromTasks = useCallback((rows: TaskRecord[]) => {
    const ordered = rows.slice().sort((a, b) => taskTimestamp(b) - taskTimestamp(a));
    for (const row of ordered) {
      const payload = extractPipelineResponse(row);
      if (!payload) continue;
      startTransition(() => {
        setLatestPipeline(payload);
      });
      recordStateUpdate("latestPipeline");
      return;
    }
  }, []);

  const upsertTaskFromEvent = useCallback((payload: Record<string, unknown>, eventSessionId?: string) => {
    const rawTask = toObject(payload.task);
    const source = Object.keys(rawTask).length > 0 ? rawTask : payload;
    const taskId = String(source.task_id ?? payload.task_id ?? "").trim();
    if (!taskId) return;
    const parentTaskId = String(source.parent_task_id ?? payload.parent_task_id ?? "").trim();
    const nextTask: TaskRecord = {
      task_id: taskId,
      parent_task_id: parentTaskId || undefined,
      task_type: String(source.task_type ?? source.type ?? payload.type ?? "task"),
      status: String(source.status ?? payload.status ?? "running"),
      progress: Number(source.progress ?? payload.progress ?? 0),
      message: String(source.message ?? payload.message ?? ""),
      result: toObject(source.result),
      result_ref: toObject(source.result_ref),
      meta: toObject(source.meta),
      created_at: String(source.created_at ?? ""),
      updated_at: String(source.updated_at ?? ""),
      error: source.error ? String(source.error) : null,
    };
    upsertTask(nextTask);
    syncLatestPipeline(nextTask);
    const sessionId = String(eventSessionId ?? source.session_id ?? nextTask.meta?.session_id ?? "").trim();
    if (sessionId && !["workbench", "pipeline", "sse", "global"].includes(sessionId.toLowerCase())) {
      addActiveTask(sessionId, taskId);
      if (isTaskTerminal(nextTask.status)) {
        syncTaskTerminalState(sessionId, taskId, nextTask.status);
      }
    }
    recordStateUpdate("tasks");
  }, [addActiveTask, syncLatestPipeline, syncTaskTerminalState, upsertTask]);

  const flushEventBuffer = useCallback(() => {
    if (eventBufferRef.current.length === 0) return;
    const pending = eventBufferRef.current;
    eventBufferRef.current = [];
    startTransition(() => {
      prependEvents([...pending].reverse());
    });
    recordStateUpdate("events");
  }, [prependEvents]);

  const enqueueEvent = useCallback(
    (event: SseEvent) => {
      eventBufferRef.current.push(event);
      if (eventFlushTimerRef.current) return;
      eventFlushTimerRef.current = setTimeout(() => {
        eventFlushTimerRef.current = null;
        flushEventBuffer();
      }, 120);
    },
    [flushEventBuffer]
  );

  const refreshRiskApprovals = useCallback(async () => {
    try {
      const [riskRes, approvalsRes] = await Promise.all([api.getRiskStatus(), api.getApprovals()]);
      setRiskSnapshot(riskRes);
      replaceApprovals(approvalsRes);
      recordStateUpdate("risk");
      recordStateUpdate("approvals");
    } catch {
      // keep silent for realtime refresh failures
    }
  }, [replaceApprovals, setRiskSnapshot]);

  useEffect(() => {
    setCatalogOwnership("legacy-workbench");
    setRiskOwnership("legacy-workbench");
  }, [setCatalogOwnership, setRiskOwnership]);

  useEffect(() => {
    installDomMutationGuard();
  }, []);

  useEffect(() => {
    recordStateUpdate("mode");
  }, [mode]);

  const refreshCore = useCallback(
    async (options?: RefreshOptions) => {
      const silent = options?.silent ?? false;
      if (silent) {
        setRefreshingCore(true);
        recordStateUpdate("refreshingCore");
      } else {
        setLoadingCore(true);
        recordStateUpdate("loadingCore");
      }

      try {
        const [tasksRes, datasetsRes, runsRes, strategiesRes, riskRes, approvalsRes] = await Promise.all([
          api.getTasks(),
          api.getDatasets(),
          api.getRuns(),
          api.getStrategies(),
          api.getRiskStatus(),
          api.getApprovals(),
        ]);

        replaceTasks(tasksRes);
        for (const row of tasksRes) {
          const sessionId = String((toObject(row.meta).session_id ?? "")).trim();
          if (!sessionId) continue;
          addActiveTask(sessionId, row.task_id);
          if (isTaskTerminal(row.status)) {
            syncTaskTerminalState(sessionId, row.task_id, row.status);
          }
        }
        syncLatestPipelineFromTasks(tasksRes);
        setCatalogDatasets(datasetsRes.slice().reverse());
        setCatalogRuns(runsRes);
        setCatalogStrategies(strategiesRes);
        setRiskSnapshot(riskRes);
        replaceApprovals(approvalsRes);
        setCoreError(null);
        recordStateUpdate("tasks");
        recordStateUpdate("datasets");
        recordStateUpdate("runs");
        recordStateUpdate("strategies");
        recordStateUpdate("risk");
        recordStateUpdate("approvals");
      } catch (err) {
        const errorMessage = err instanceof Error ? err.message : messages.toast.unknownError;
        setCoreError(errorMessage);
        if (!silent) {
          pushToast("Refresh failed", errorMessage, "error");
        }
      } finally {
        if (silent) {
          setRefreshingCore(false);
          recordStateUpdate("refreshingCore");
        } else {
          setLoadingCore(false);
          recordStateUpdate("loadingCore");
        }
      }
    },
    [
      addActiveTask,
      pushToast,
      replaceApprovals,
      replaceTasks,
      setCatalogDatasets,
      setCatalogRuns,
      setCatalogStrategies,
      setRiskSnapshot,
      syncLatestPipelineFromTasks,
      syncTaskTerminalState,
    ]
  );

  const scheduleCoreRefresh = useCallback(() => {
    if (refreshTimerRef.current) return;
    refreshTimerRef.current = setTimeout(() => {
      refreshTimerRef.current = null;
      void refreshCore({ silent: true });
    }, 600);
  }, [refreshCore]);

  const selectSession = useCallback(async (sessionId: string) => {
    syncActiveSession(sessionId);
  }, [syncActiveSession]);

  useEffect(() => {
    void refreshCore();

    const timer = setInterval(() => {
      void refreshCore({ silent: true });
    }, 30_000);

    return () => {
      clearInterval(timer);
      if (refreshTimerRef.current) {
        clearTimeout(refreshTimerRef.current);
        refreshTimerRef.current = null;
      }
      if (eventFlushTimerRef.current) {
        clearTimeout(eventFlushTimerRef.current);
        eventFlushTimerRef.current = null;
      }
    };
  }, [refreshCore]);

  useEffect(() => {
    const onBeforeUnload = () => recordBeforeUnload();
    const onVisibility = () => recordVisibilityChange(document.visibilityState === "hidden");
    window.addEventListener("beforeunload", onBeforeUnload);
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      window.removeEventListener("beforeunload", onBeforeUnload);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, []);

  useEffect(() => {
    const unsub = subscribeEvents({
      onEvent: (ev) => {
        const eventId = String(ev.event_id ?? "").trim();
        if (eventId) {
          if (seenEventIdsRef.current.has(eventId)) return;
          seenEventIdsRef.current.add(eventId);
          seenEventOrderRef.current.push(eventId);
          if (seenEventOrderRef.current.length > 500) {
            const old = seenEventOrderRef.current.shift();
            if (old) seenEventIdsRef.current.delete(old);
          }
        }
        enqueueEvent(ev);

        if (["task.created", "task.progress", "task.heartbeat", "task.done", "task.error"].includes(ev.type)) {
          upsertTaskFromEvent(toObject(ev.payload), String(ev.session_id ?? ""));
        }

        if (["task.created", "task.done", "task.error", "report.ready"].includes(ev.type)) {
          scheduleCoreRefresh();
        }

        if (["task.done", "task.error", "chat.done"].includes(ev.type)) {
          const eventSessionId = String(ev.session_id ?? "").trim();
          if (eventSessionId && !["workbench", "pipeline", "sse", "global"].includes(eventSessionId.toLowerCase())) {
            recordStateUpdate("chatSessions");
            recordStateUpdate("chatTurns");
          }
        }

        if (ev.type === "risk.event") {
          void refreshRiskApprovals();
          const payload = ev.payload ?? {};
          const message = String(payload.message ?? payload.event_type ?? "Risk event detected");
          pushToast("Risk event", message, "error");
        }

        if (ev.type === "approval.status_changed") {
          void refreshRiskApprovals();
          const payload = ev.payload ?? {};
          const requestId = String(payload.request_id ?? "");
          const status = String(payload.status ?? "");
          if (requestId && status) {
            pushToast("Approval status changed", `${requestId} -> ${status}`, "default");
          }
        }
      },
      onError: () => {
        pushToast("Realtime stream disconnected", "SSE disconnected. Automatic reconnect in progress.", "error");
      },
      onStatus: (status, detail) => {
        if (status === "open") {
          recordSseOpen();
          startTransition(() => {
            setSseConnectionState("open");
          });
          void refreshCore({ silent: true });
          return;
        }
        if (status === "close") {
          recordSseClose();
          startTransition(() => {
            setSseConnectionState("closed");
          });
          return;
        }
        if (status === "error") {
          recordSseError();
          startTransition(() => {
            setSseConnectionState("error");
          });
          return;
        }
        if (status === "reconnect") {
          recordSseReconnect(detail?.delayMs ?? 0);
          startTransition(() => {
            setSseConnectionState("reconnecting");
          });
        }
      },
    });
    return () => {
      unsub();
    };
  }, [activeSessionId, enqueueEvent, pushToast, refreshCore, refreshRiskApprovals, scheduleCoreRefresh, upsertTaskFromEvent]);

  useEffect(() => {
    const taskIds = useTaskStore.getState().listAllActiveTaskIds();
    if (taskIds.length === 0) return;
    let cancelled = false;
    void (async () => {
      for (const taskId of taskIds) {
        try {
          const row = await api.getTask(taskId);
          if (cancelled) return;
          upsertTask(row);
          syncLatestPipeline(row);
          const sessionId = String((toObject(row.meta).session_id ?? "")).trim();
          if (sessionId) {
            syncTaskTerminalState(sessionId, row.task_id, row.status);
          }
        } catch {
          // keep stale local cache entry; API may have pruned old tasks
        }
      }
      recordStateUpdate("tasks");
    })();
    return () => {
      cancelled = true;
    };
  }, [syncLatestPipeline, syncTaskTerminalState, upsertTask]);

  const pollTask = useCallback(
    async (taskId: string) => {
      let done = false;
      while (!done) {
        const row = await api.getTask(taskId);
        upsertTask(row);
        syncLatestPipeline(row);
        recordStateUpdate("tasks");

        done = row.status === "done" || row.status === "failed" || row.status === "error";
        if (!done) {
          await new Promise((resolve) => setTimeout(resolve, 350));
        }
      }
      await refreshCore({ silent: true });
    },
    [refreshCore, syncLatestPipeline, upsertTask]
  );

  const generateDataset = useCallback(async () => {
    try {
      const task = await api.generateDataset({
        dataset_id: "frontend_dataset",
        market: "US",
        symbol: "AAPL",
        start: "2024-01-01",
        end: "2024-03-31",
        seed: 42,
        base_price: 100,
      });
      pushToast("Task created", "Generating dataset...");
      await pollTask(task.task_id);
      pushToast("Dataset ready", undefined, "success");
    } catch (err) {
      pushToast("Dataset generation failed", err instanceof Error ? err.message : messages.toast.unknownError, "error");
    }
  }, [pollTask, pushToast]);

  const runBacktest = useCallback(async () => {
    try {
      const latestDataset = datasets[0]?.dataset_version;
      const task = await api.runBacktest({
        dataset_version: latestDataset ?? null,
        strategy_id: "frontend_strategy",
        strategy_version: "1.0.0",
        market: "US",
        start: "2024-01-01",
        end: "2024-03-31",
      });
      pushToast("Task created", "Running backtest...");
      await pollTask(task.task_id);
      pushToast("Backtest completed", undefined, "success");
    } catch (err) {
      pushToast("Backtest failed", err instanceof Error ? err.message : messages.toast.unknownError, "error");
    }
  }, [datasets, pollTask, pushToast]);

  const runPipeline = useCallback(
    async (
      question: string,
      market = "US",
      options?: {
        planId?: string;
        constraints?: Record<string, unknown>;
        migrationPreflightConfirmed?: boolean;
        autoAdjustForMarketRules?: boolean;
      }
    ) => {
      const sessionId = (activeSessionId || "pipeline").trim();
      const task = await api.runPlanSubmit({
        question,
        market,
        plan_id: options?.planId,
        constraints: options?.constraints ?? {},
        max_drawdown_target: 0.1,
        run_paper_trade: true,
        experiments: 3,
        migration_preflight_confirmed: options?.migrationPreflightConfirmed ?? false,
        auto_adjust_for_market_rules: options?.autoAdjustForMarketRules ?? false,
        session_id: sessionId,
      });
      upsertTask(task);
      addActiveTask(sessionId, task.task_id);
      await refreshCore({ silent: true });
      return task;
    },
    [activeSessionId, addActiveTask, refreshCore, upsertTask]
  );

  const sendChat = useCallback(
    async (message: string) => {
      // Deprecated compatibility path: `/chat` now coordinates send execution from ChatWorkspaceProvider.
      return executeChatSend({
        message,
        sessionIdForRequest: activeSessionId,
        includeDebug: mode === "developer",
        currentRiskSnapshot: risk,
        syncActiveSession,
        upsertChatResponse,
        setRiskSnapshot,
        upsertApproval,
        prependEvents,
        addActiveTask,
        upsertTask,
        syncTaskTerminalState,
      });
    },
    [
      activeSessionId,
      addActiveTask,
      mode,
      risk,
      prependEvents,
      setRiskSnapshot,
      syncActiveSession,
      syncTaskTerminalState,
      upsertChatResponse,
      upsertApproval,
      upsertTask,
    ]
  );

  const restoreTraceContext = useCallback(
    async (traceId: string) => {
      const bundle = await api.restoreTrace(traceId, activeSessionId ?? undefined);
      const restoredSessionId = String(bundle.session_state?.session_id || "");
      if (restoredSessionId) {
        syncActiveSession(restoredSessionId);
        setRestoreContext({
          sessionId: restoredSessionId,
          traceId,
          restoredAt: new Date().toISOString(),
        });
        recordStateUpdate("chatTurns");
      }
      pushToast("Context restored", bundle.summary, bundle.partial_restore ? "default" : "success");
      return bundle;
    },
    [activeSessionId, pushToast, setRestoreContext, syncActiveSession]
  );

  const setKillSwitch = useCallback(async (enabled: boolean) => {
    await setKillSwitchAction(enabled);
  }, [setKillSwitchAction]);

  const setLiveUnlock = useCallback(async (enabled: boolean) => {
    await setLiveUnlockAction(enabled);
  }, [setLiveUnlockAction]);

  const setPaperRunning = useCallback(async (enabled: boolean) => {
    await setPaperRunningAction(enabled);
  }, [setPaperRunningAction]);

  const requestApproval = useCallback(
    async (payload: {
      target: "live_trading" | "paper_trading";
      use_case?: string;
      plan_id?: string;
      evidence_pack_id?: string;
      session_id?: string;
      risk_statement_ack?: boolean;
    }) => {
      await requestApprovalAction(payload);
    },
    [requestApprovalAction]
  );

  const approveApproval = useCallback(async (requestId: string) => {
    await approveApprovalAction(requestId);
  }, [approveApprovalAction]);

  const enableApproval = useCallback(async (requestId: string) => {
    await enableApprovalAction(requestId);
  }, [enableApprovalAction]);

  const revokeApproval = useCallback(async (requestId: string) => {
    await revokeApprovalAction(requestId);
  }, [revokeApprovalAction]);

  const value = useMemo<WorkbenchContextShape>(
    () => ({
      mode,
      setMode,
      loadingCore,
      refreshingCore,
      coreError,
      datasets,
      runs,
      strategies,
      risk,
      approvals,
      latestDatasetVersion: datasets[0]?.dataset_version ?? null,
      latestStrategyVersion: runs[0]?.strategy_version ?? null,
      latestPipeline,
      activeSessionId,
      refreshCore: async () => refreshCore(),
      generateDataset,
      runBacktest,
      runPipeline,
      sendChat,
      restoreTraceContext,
      pushToast,
      setKillSwitch,
      setLiveUnlock,
      setPaperRunning,
      requestApproval,
      approveApproval,
      enableApproval,
      revokeApproval,
    }),
    [
      mode,
      loadingCore,
      refreshingCore,
      coreError,
      datasets,
      runs,
      strategies,
      risk,
      approvals,
      latestPipeline,
      activeSessionId,
      refreshCore,
      generateDataset,
      runBacktest,
      runPipeline,
      sendChat,
      restoreTraceContext,
      pushToast,
      setKillSwitch,
      setLiveUnlock,
      setPaperRunning,
      requestApproval,
      approveApproval,
      enableApproval,
      revokeApproval,
    ]
  );

  const chatActions = useMemo<WorkbenchChatActionsContextShape>(
    () => ({
      selectSession,
      syncActiveSession,
    }),
    [selectSession, syncActiveSession]
  );

  return (
    <WorkbenchContext.Provider value={value}>
      <WorkbenchChatActionsContext.Provider value={chatActions}>{children}</WorkbenchChatActionsContext.Provider>
    </WorkbenchContext.Provider>
  );
}

export function useWorkbench() {
  const ctx = useContext(WorkbenchContext);
  if (!ctx) {
    throw new Error("useWorkbench must be used within WorkbenchProvider");
  }
  return ctx;
}

export function useWorkbenchChat() {
  const ctx = useContext(WorkbenchChatActionsContext);
  if (!ctx) {
    throw new Error("useWorkbenchChat must be used within WorkbenchProvider");
  }
  const events = useWorkbenchChatStore((state) => state.events);
  const sseConnectionState = useWorkbenchChatStore((state) => state.sseConnectionState);
  return {
    events,
    sseConnectionState,
    selectSession: ctx.selectSession,
    syncActiveSession: ctx.syncActiveSession,
  };
}

export function useWorkbenchTasks() {
  const { tasks, activeTasksCount } = useTaskRealtimeState();
  return { tasks, activeTasksCount };
}
