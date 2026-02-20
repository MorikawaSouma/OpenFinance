"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

import { api } from "@/lib/api";
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
import { messages } from "@/lib/messages";
import type {
  ApprovalRequest,
  ChatResponse,
  ChatSessionSummary,
  ChatTurn,
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
import { ToastViewport, type ToastItem } from "@/components/ui/toast";

type WorkbenchContextShape = {
  mode: Mode;
  setMode: (next: Mode) => void;
  loadingCore: boolean;
  refreshingCore: boolean;
  tasks: TaskRecord[];
  datasets: DatasetEntry[];
  runs: RunSummary[];
  strategies: StrategySummary[];
  risk: RiskStatus | null;
  approvals: ApprovalRequest[];
  events: SseEvent[];
  activeTasksCount: number;
  latestDatasetVersion: string | null;
  latestStrategyVersion: string | null;
  latestPipeline: PipelineResponse | null;
  chatSessions: ChatSessionSummary[];
  activeSessionId: string | null;
  chatTurns: ChatTurn[];
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
  ) => Promise<PipelineResponse>;
  sendChat: (message: string) => Promise<ChatResponse>;
  selectSession: (sessionId: string) => Promise<void>;
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

const WorkbenchContext = createContext<WorkbenchContextShape | null>(null);

function uid() {
  return Math.random().toString(36).slice(2, 10);
}

type RefreshOptions = {
  silent?: boolean;
};

export function WorkbenchProvider({ children }: { children: ReactNode }) {
  const [mode, setMode] = useState<Mode>("user");

  const [loadingCore, setLoadingCore] = useState(true);
  const [refreshingCore, setRefreshingCore] = useState(false);
  const [tasks, setTasks] = useState<TaskRecord[]>([]);
  const [datasets, setDatasets] = useState<DatasetEntry[]>([]);
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [strategies, setStrategies] = useState<StrategySummary[]>([]);
  const [risk, setRisk] = useState<RiskStatus | null>(null);
  const [approvals, setApprovals] = useState<ApprovalRequest[]>([]);
  const [events, setEvents] = useState<SseEvent[]>([]);
  const [latestPipeline, setLatestPipeline] = useState<PipelineResponse | null>(null);

  const [chatSessions, setChatSessions] = useState<ChatSessionSummary[]>([]);
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [chatTurns, setChatTurns] = useState<ChatTurn[]>([]);

  const [toasts, setToasts] = useState<ToastItem[]>([]);

  const eventBufferRef = useRef<SseEvent[]>([]);
  const eventFlushTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const refreshTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const pushToast = useCallback((title: string, description?: string, variant?: ToastItem["variant"]) => {
    const id = uid();
    setToasts((prev) => [...prev, { id, title, description, variant }].slice(-4));
    setTimeout(() => {
      setToasts((prev) => prev.filter((item) => item.id !== id));
    }, 3500);
  }, []);

  const dismissToast = useCallback((id: string) => {
    setToasts((prev) => prev.filter((item) => item.id !== id));
  }, []);

  const flushEventBuffer = useCallback(() => {
    if (eventBufferRef.current.length === 0) return;
    const pending = eventBufferRef.current;
    eventBufferRef.current = [];
    setEvents((prev) => {
      const next = [...pending.reverse(), ...prev].slice(0, 120);
      return next;
    });
    recordStateUpdate("events");
  }, []);

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
      setRisk(riskRes);
      setApprovals(approvalsRes);
      recordStateUpdate("risk");
      recordStateUpdate("approvals");
    } catch {
      // keep silent for realtime refresh failures
    }
  }, []);

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

        setTasks(tasksRes);
        setDatasets(datasetsRes.slice().reverse());
        setRuns(runsRes);
        setStrategies(strategiesRes);
        setRisk(riskRes);
        setApprovals(approvalsRes);
        recordStateUpdate("tasks");
        recordStateUpdate("datasets");
        recordStateUpdate("runs");
        recordStateUpdate("strategies");
        recordStateUpdate("risk");
        recordStateUpdate("approvals");
      } catch (err) {
        if (!silent) {
          pushToast("Refresh failed", err instanceof Error ? err.message : messages.toast.unknownError, "error");
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
    [pushToast]
  );

  const scheduleCoreRefresh = useCallback(() => {
    if (refreshTimerRef.current) return;
    refreshTimerRef.current = setTimeout(() => {
      refreshTimerRef.current = null;
      void refreshCore({ silent: true });
    }, 600);
  }, [refreshCore]);

  const loadChatSessions = useCallback(async () => {
    try {
      const rows = await api.getChatSessions();
      setChatSessions(rows);
      recordStateUpdate("chatSessions");
      if (!activeSessionId && rows.length > 0) {
        setActiveSessionId(rows[0].session_id);
        const turns = await api.getChatSessionTurns(rows[0].session_id);
        setChatTurns(turns);
        recordStateUpdate("activeSessionId");
        recordStateUpdate("chatTurns");
      }
    } catch {
      // keep silent in background
    }
  }, [activeSessionId]);

  const selectSession = useCallback(async (sessionId: string) => {
    setActiveSessionId(sessionId);
    recordStateUpdate("activeSessionId");
    const turns = await api.getChatSessionTurns(sessionId);
    setChatTurns(turns);
    recordStateUpdate("chatTurns");
  }, []);

  useEffect(() => {
    void refreshCore();
    void loadChatSessions();

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
  }, [loadChatSessions, refreshCore]);

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
        enqueueEvent(ev);

        if (["task.created", "task.done", "report.ready"].includes(ev.type)) {
          scheduleCoreRefresh();
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
        if (status === "open") recordSseOpen();
        if (status === "close") recordSseClose();
        if (status === "error") recordSseError();
        if (status === "reconnect") recordSseReconnect(detail?.delayMs ?? 0);
      },
    });
    return () => {
      unsub();
    };
  }, [enqueueEvent, pushToast, refreshRiskApprovals, scheduleCoreRefresh]);

  useEffect(() => {
    const savedMode = localStorage.getItem("of_mode");
    if (savedMode === "developer" || savedMode === "user") {
      setMode(savedMode);
      recordStateUpdate("mode");
    }
  }, []);

  useEffect(() => {
    localStorage.setItem("of_mode", mode);
  }, [mode]);

  const pollTask = useCallback(
    async (taskId: string) => {
      let done = false;
      while (!done) {
        const row = await api.getTask(taskId);
        setTasks((prev) => {
          const map = new Map(prev.map((item) => [item.task_id, item]));
          map.set(row.task_id, row);
          return [...map.values()].sort((a, b) => (a.task_id < b.task_id ? 1 : -1));
        });
        recordStateUpdate("tasks");

        done = row.status === "done" || row.status === "failed";
        if (!done) {
          await new Promise((resolve) => setTimeout(resolve, 350));
        }
      }
      await refreshCore({ silent: true });
    },
    [refreshCore]
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
      const result = await api.runPlan({
        question,
        market,
        plan_id: options?.planId,
        constraints: options?.constraints ?? {},
        max_drawdown_target: 0.1,
        run_paper_trade: true,
        experiments: 3,
        migration_preflight_confirmed: options?.migrationPreflightConfirmed ?? false,
        auto_adjust_for_market_rules: options?.autoAdjustForMarketRules ?? false,
      });
      setLatestPipeline(result);
      recordStateUpdate("latestPipeline");
      await refreshCore({ silent: true });
      return result;
    },
    [refreshCore]
  );

  const sendChat = useCallback(
    async (message: string) => {
      const resp = await api.sendChat({ message, session_id: activeSessionId });
      setActiveSessionId(resp.session_id);
      setChatTurns(resp.turns);
      recordStateUpdate("activeSessionId");
      recordStateUpdate("chatTurns");
      await loadChatSessions();
      return resp;
    },
    [activeSessionId, loadChatSessions]
  );

  const restoreTraceContext = useCallback(
    async (traceId: string) => {
      const bundle = await api.restoreTrace(traceId, activeSessionId ?? undefined);
      const restoredSessionId = String(bundle.session_state?.session_id || "");
      if (restoredSessionId) {
        setActiveSessionId(restoredSessionId);
        recordStateUpdate("activeSessionId");
        const turns = await api.getChatSessionTurns(restoredSessionId);
        setChatTurns(turns);
        recordStateUpdate("chatTurns");
      }
      await loadChatSessions();
      await refreshCore({ silent: true });
      pushToast("Context restored", bundle.summary, bundle.partial_restore ? "default" : "success");
      return bundle;
    },
    [activeSessionId, loadChatSessions, pushToast, refreshCore]
  );

  const setKillSwitch = useCallback(
    async (enabled: boolean) => {
      try {
        const status = await api.setKillSwitch(enabled);
        setRisk(status);
        recordStateUpdate("risk");
        pushToast("Kill switch updated", enabled ? "Kill switch ON" : "Kill switch OFF", "success");
      } catch (err) {
        pushToast("Kill switch update failed", err instanceof Error ? err.message : messages.toast.unknownError, "error");
      }
    },
    [pushToast]
  );

  const setLiveUnlock = useCallback(
    async (enabled: boolean) => {
      try {
        const status = await api.setLiveUnlock(enabled);
        setRisk(status);
        recordStateUpdate("risk");
        pushToast(
          "Live lock updated",
          status.live_trading_enabled ? "Live trading is enabled." : "Live trading remains locked.",
          status.live_trading_enabled ? "success" : "default"
        );
      } catch (err) {
        pushToast("Live lock update failed", err instanceof Error ? err.message : messages.toast.unknownError, "error");
      }
    },
    [pushToast]
  );

  const setPaperRunning = useCallback(
    async (enabled: boolean) => {
      try {
        const status = await api.setPaperRunning(enabled);
        setRisk(status);
        recordStateUpdate("risk");
        pushToast("Paper trading status updated", enabled ? "Paper trading started." : "Paper trading stopped.", "success");
      } catch (err) {
        pushToast("Paper trading update failed", err instanceof Error ? err.message : messages.toast.unknownError, "error");
      }
    },
    [pushToast]
  );

  const requestApproval = useCallback(
    async (payload: {
      target: "live_trading" | "paper_trading";
      use_case?: string;
      plan_id?: string;
      evidence_pack_id?: string;
      session_id?: string;
      risk_statement_ack?: boolean;
    }) => {
      try {
        const row = await api.requestApproval(payload);
        setApprovals((prev) => [row, ...prev.filter((item) => item.request_id !== row.request_id)]);
        recordStateUpdate("approvals");
        await refreshCore({ silent: true });
        pushToast("Approval request submitted", `${payload.target} status: ${row.status}`, "success");
      } catch (err) {
        pushToast("Approval request failed", err instanceof Error ? err.message : messages.toast.unknownError, "error");
      }
    },
    [pushToast, refreshCore]
  );

  const approveApproval = useCallback(
    async (requestId: string) => {
      try {
        const row = await api.approveApproval(requestId);
        setApprovals((prev) => [row, ...prev.filter((item) => item.request_id !== row.request_id)]);
        recordStateUpdate("approvals");
        await refreshCore({ silent: true });
        pushToast("Approval updated", `${requestId} -> approved`, "success");
      } catch (err) {
        pushToast("Approve failed", err instanceof Error ? err.message : messages.toast.unknownError, "error");
      }
    },
    [pushToast, refreshCore]
  );

  const enableApproval = useCallback(
    async (requestId: string) => {
      try {
        const row = await api.enableApproval(requestId);
        setApprovals((prev) => [row, ...prev.filter((item) => item.request_id !== row.request_id)]);
        recordStateUpdate("approvals");
        await refreshCore({ silent: true });
        pushToast("Approval updated", `${requestId} -> enabled`, "success");
      } catch (err) {
        pushToast("Enable failed", err instanceof Error ? err.message : messages.toast.unknownError, "error");
      }
    },
    [pushToast, refreshCore]
  );

  const revokeApproval = useCallback(
    async (requestId: string) => {
      try {
        const row = await api.revokeApproval(requestId);
        setApprovals((prev) => [row, ...prev.filter((item) => item.request_id !== row.request_id)]);
        recordStateUpdate("approvals");
        await refreshCore({ silent: true });
        pushToast("Approval updated", `${requestId} -> revoked`, "success");
      } catch (err) {
        pushToast("Revoke failed", err instanceof Error ? err.message : messages.toast.unknownError, "error");
      }
    },
    [pushToast, refreshCore]
  );

  const value = useMemo<WorkbenchContextShape>(
    () => ({
      mode,
      setMode,
      loadingCore,
      refreshingCore,
      tasks,
      datasets,
      runs,
      strategies,
      risk,
      approvals,
      events,
      activeTasksCount: tasks.filter((item) => item.status === "running").length,
      latestDatasetVersion: datasets[0]?.dataset_version ?? null,
      latestStrategyVersion: runs[0]?.strategy_version ?? null,
      latestPipeline,
      chatSessions,
      activeSessionId,
      chatTurns,
      refreshCore: async () => refreshCore(),
      generateDataset,
      runBacktest,
      runPipeline,
      sendChat,
      restoreTraceContext,
      selectSession,
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
      tasks,
      datasets,
      runs,
      strategies,
      risk,
      approvals,
      events,
      latestPipeline,
      chatSessions,
      activeSessionId,
      chatTurns,
      refreshCore,
      generateDataset,
      runBacktest,
      runPipeline,
      sendChat,
      restoreTraceContext,
      selectSession,
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

  return (
    <WorkbenchContext.Provider value={value}>
      {children}
      <ToastViewport items={toasts} onDismiss={dismissToast} />
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
