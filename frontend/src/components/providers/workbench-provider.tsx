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
import { messages } from "@/lib/messages";
import { isTaskTerminal, useTaskStore } from "@/lib/task-store";
import { installDomMutationGuard } from "@/lib/dom-guard";
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
  coreError: string | null;
  tasks: TaskRecord[];
  datasets: DatasetEntry[];
  runs: RunSummary[];
  strategies: StrategySummary[];
  risk: RiskStatus | null;
  approvals: ApprovalRequest[];
  events: SseEvent[];
  sseConnectionState: "connecting" | "open" | "closed" | "error" | "reconnecting";
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
  ) => Promise<TaskRecord>;
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

function extractTaskIdsFromChatResponse(response: ChatResponse): string[] {
  const debug = toObject(response.debug);
  const direct = [
    String(debug.task_id ?? "").trim(),
    String(debug.parent_task_id ?? "").trim(),
    String(debug.us_parent_task_id ?? "").trim(),
    String(debug.jp_parent_task_id ?? "").trim(),
  ].filter((row) => row.length > 0);

  const childTaskIdsRaw = debug.child_task_ids;
  const childTaskIds = Array.isArray(childTaskIdsRaw)
    ? childTaskIdsRaw.map((row) => String(row ?? "").trim()).filter((row) => row.length > 0)
    : [];
  return Array.from(new Set([...direct, ...childTaskIds]));
}

type RefreshOptions = {
  silent?: boolean;
};

export function WorkbenchProvider({ children }: { children: ReactNode }) {
  const [mode, setMode] = useState<Mode>("user");

  const [loadingCore, setLoadingCore] = useState(true);
  const [refreshingCore, setRefreshingCore] = useState(false);
  const [coreError, setCoreError] = useState<string | null>(null);
  const [datasets, setDatasets] = useState<DatasetEntry[]>([]);
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [strategies, setStrategies] = useState<StrategySummary[]>([]);
  const [risk, setRisk] = useState<RiskStatus | null>(null);
  const [approvals, setApprovals] = useState<ApprovalRequest[]>([]);
  const [events, setEvents] = useState<SseEvent[]>([]);
  const [sseConnectionState, setSseConnectionState] = useState<
    "connecting" | "open" | "closed" | "error" | "reconnecting"
  >("connecting");
  const [latestPipeline, setLatestPipeline] = useState<PipelineResponse | null>(null);

  const [chatSessions, setChatSessions] = useState<ChatSessionSummary[]>([]);
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [chatTurns, setChatTurns] = useState<ChatTurn[]>([]);

  const [toasts, setToasts] = useState<ToastItem[]>([]);
  const upsertChatResponse = useChatSessionStore((state) => state.upsertFromResponse);
  const hydrateSessionTurns = useChatSessionStore((state) => state.hydrateSessionTurns);
  const tasksById = useTaskStore((state) => state.tasksById);
  const upsertTask = useTaskStore((state) => state.upsertTask);
  const replaceTasks = useTaskStore((state) => state.replaceTasks);
  const addActiveTask = useTaskStore((state) => state.addActiveTask);
  const syncTaskTerminalState = useTaskStore((state) => state.syncTaskTerminalState);
  const tasks = useMemo(
    () => Object.values(tasksById).sort((a, b) => taskTimestamp(b) - taskTimestamp(a)),
    [tasksById]
  );

  useEffect(() => {
    const pipelineTask = tasks.find((row) => {
      if (String(row.task_type) !== "pipeline_run") return false;
      if (String(row.status).toLowerCase() !== "done") return false;
      const result = toObject(row.result);
      return Object.keys(toObject(result.pipeline_response)).length > 0;
    });
    if (!pipelineTask) return;
    const payload = toObject(toObject(pipelineTask.result).pipeline_response);
    if (Object.keys(payload).length === 0) return;
    try {
      setLatestPipeline(payload as unknown as PipelineResponse);
      recordStateUpdate("latestPipeline");
    } catch {
      // ignore malformed payload
    }
  }, [tasks]);

  const eventBufferRef = useRef<SseEvent[]>([]);
  const seenEventOrderRef = useRef<string[]>([]);
  const seenEventIdsRef = useRef<Set<string>>(new Set());
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
    const sessionId = String(eventSessionId ?? source.session_id ?? nextTask.meta?.session_id ?? "").trim();
    if (sessionId && !["workbench", "pipeline", "sse", "global"].includes(sessionId.toLowerCase())) {
      addActiveTask(sessionId, taskId);
      if (isTaskTerminal(nextTask.status)) {
        syncTaskTerminalState(sessionId, taskId, nextTask.status);
      }
    }
    recordStateUpdate("tasks");
  }, [addActiveTask, syncTaskTerminalState, upsertTask]);

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

  useEffect(() => {
    installDomMutationGuard();
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

        replaceTasks(tasksRes);
        for (const row of tasksRes) {
          const sessionId = String((toObject(row.meta).session_id ?? "")).trim();
          if (!sessionId) continue;
          addActiveTask(sessionId, row.task_id);
          if (isTaskTerminal(row.status)) {
            syncTaskTerminalState(sessionId, row.task_id, row.status);
          }
        }
        setDatasets(datasetsRes.slice().reverse());
        setRuns(runsRes);
        setStrategies(strategiesRes);
        setRisk(riskRes);
        setApprovals(approvalsRes);
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
    [addActiveTask, pushToast, replaceTasks, syncTaskTerminalState]
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
        hydrateSessionTurns(rows[0].session_id, turns);
        setChatTurns(turns);
        recordStateUpdate("activeSessionId");
        recordStateUpdate("chatTurns");
      }
    } catch {
      // keep silent in background
    }
  }, [activeSessionId, hydrateSessionTurns]);

  const selectSession = useCallback(async (sessionId: string) => {
    setActiveSessionId(sessionId);
    setChatTurns([]);
    recordStateUpdate("activeSessionId");
    recordStateUpdate("chatTurns");
    const turns = await api.getChatSessionTurns(sessionId);
    hydrateSessionTurns(sessionId, turns);
    setChatTurns(turns);
    recordStateUpdate("chatTurns");
  }, [hydrateSessionTurns]);

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
          if (eventSessionId && activeSessionId && eventSessionId === activeSessionId) {
            void api.getChatSessionTurns(eventSessionId).then((turns) => {
              hydrateSessionTurns(eventSessionId, turns);
              setChatTurns(turns);
              recordStateUpdate("chatTurns");
            }).catch(() => undefined);
          }
          if (eventSessionId && !["workbench", "pipeline", "sse", "global"].includes(eventSessionId.toLowerCase())) {
            void loadChatSessions();
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
          setSseConnectionState("open");
          void refreshCore({ silent: true });
          return;
        }
        if (status === "close") {
          recordSseClose();
          setSseConnectionState("closed");
          return;
        }
        if (status === "error") {
          recordSseError();
          setSseConnectionState("error");
          return;
        }
        if (status === "reconnect") {
          recordSseReconnect(detail?.delayMs ?? 0);
          setSseConnectionState("reconnecting");
        }
      },
    });
    return () => {
      unsub();
    };
  }, [activeSessionId, enqueueEvent, hydrateSessionTurns, loadChatSessions, pushToast, refreshCore, refreshRiskApprovals, scheduleCoreRefresh, upsertTaskFromEvent]);

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
  }, [syncTaskTerminalState, upsertTask]);

  const pollTask = useCallback(
    async (taskId: string) => {
      let done = false;
      while (!done) {
        const row = await api.getTask(taskId);
        upsertTask(row);
        recordStateUpdate("tasks");

        done = row.status === "done" || row.status === "failed" || row.status === "error";
        if (!done) {
          await new Promise((resolve) => setTimeout(resolve, 350));
        }
      }
      await refreshCore({ silent: true });
    },
    [refreshCore, upsertTask]
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
      const resp = await api.sendChat({
        message,
        session_id: activeSessionId,
        include_debug: mode === "developer",
      });
      upsertChatResponse(resp);
      const debug = toObject(resp.debug);
      const debugReasoningSteps = debug.reasoning_steps;
      if (Array.isArray(debugReasoningSteps)) {
        for (let i = 0; i < debugReasoningSteps.length; i += 1) {
          const step = toObject(debugReasoningSteps[i]);
          const createdAt = String(step.created_at ?? new Date().toISOString());
          enqueueEvent({
            event_id: `chatresp:${resp.message_id}:reasoning:${i}`,
            type: "reasoning.step.created",
            trace_id: String(resp.trace_id ?? ""),
            session_id: String(resp.session_id ?? ""),
            timestamp: createdAt,
            payload: {
              step,
              agent_name: String(step.agent_name ?? ""),
              step_idx: Number(step.step_idx ?? i + 1),
              step_type: String(step.step_type ?? "warning"),
              title: String(step.title ?? ""),
              summary: String(step.summary ?? ""),
              evidence_refs: Array.isArray(step.evidence_refs) ? step.evidence_refs : [],
              parse_error: String(step.parse_error ?? ""),
              prompt_hash: String(step.prompt_hash ?? ""),
            },
          });
        }
        enqueueEvent({
          event_id: `chatresp:${resp.message_id}:reasoning:final`,
          type: "reasoning.trace.final",
          trace_id: String(resp.trace_id ?? ""),
          session_id: String(resp.session_id ?? ""),
          timestamp: new Date().toISOString(),
          payload: {
            agent_name: "GeneralInfo",
            steps_count: debugReasoningSteps.length,
            steps: debugReasoningSteps,
            has_parse_error: debugReasoningSteps.some((row) => Boolean(toObject(row).parse_error)),
          },
        });
      }
      const riskSnapshot = toObject(resp.risk_snapshot);
      if (Object.keys(riskSnapshot).length > 0) {
        setRisk((prev) => ({
          ...(prev ?? {
            mode: "paper",
            kill_switch_enabled: false,
            live_trading_enabled: false,
            paper_trading_enabled: false,
            risk_max_order_qty: 0,
          }),
          live_trading_enabled: Boolean(riskSnapshot.live_trading_enabled),
          paper_trading_enabled: Boolean(riskSnapshot.paper_trading_enabled),
          kill_switch_enabled: Boolean(riskSnapshot.kill_switch),
          live_approval_state: String(riskSnapshot.live_lock_status ?? prev?.live_approval_state ?? "locked"),
          current_drawdown: Number(riskSnapshot.drawdown ?? prev?.current_drawdown ?? 0),
          current_volatility: Number(riskSnapshot.volatility ?? prev?.current_volatility ?? 0),
          risk_status: String(riskSnapshot.risk_level ?? prev?.risk_status ?? "normal"),
          max_account_drawdown_limit: Number(
            toObject(riskSnapshot.limits).max_account_drawdown_limit ?? prev?.max_account_drawdown_limit ?? 0
          ),
          abnormal_volatility_limit: Number(
            toObject(riskSnapshot.limits).abnormal_volatility_limit ?? prev?.abnormal_volatility_limit ?? 0
          ),
          risk_max_order_qty: Number(toObject(riskSnapshot.limits).risk_max_order_qty ?? prev?.risk_max_order_qty ?? 0),
          updated_at: String(riskSnapshot.updated_at ?? ""),
        }));
        recordStateUpdate("risk");
      }
      const approvalsSnapshot = toObject(resp.approvals_snapshot);
      const approvalsRaw = approvalsSnapshot.items;
      if (Array.isArray(approvalsRaw)) {
        const mapped: ApprovalRequest[] = approvalsRaw
          .map((row) => toObject(row))
          .map((row) => ({
            request_id: String(row.request_id ?? ""),
            target: String(row.target ?? ""),
            action: "request_trade_enable",
            status: String(row.status ?? "pending") as ApprovalRequest["status"],
            context: {
              use_case: String(row.use_case ?? ""),
              plan_id: String(row.plan_id ?? ""),
            },
            created_at: String(row.created_at ?? ""),
            updated_at: String(row.created_at ?? ""),
            expires_at: null,
            transitions: [],
          }))
          .filter((row) => row.request_id.length > 0);
        if (mapped.length > 0) {
          setApprovals((prev) => {
            const keep = prev.filter((item) => !mapped.some((next) => next.request_id === item.request_id));
            return [...mapped, ...keep].slice(0, 30);
          });
          recordStateUpdate("approvals");
        }
      }
      setActiveSessionId(resp.session_id);
      setChatTurns(resp.turns);
      recordStateUpdate("activeSessionId");
      recordStateUpdate("chatTurns");
      const linkedTaskIds = extractTaskIdsFromChatResponse(resp);
      for (const taskId of linkedTaskIds) {
        addActiveTask(resp.session_id, taskId);
        try {
          const row = await api.getTask(taskId);
          upsertTask(row);
          syncTaskTerminalState(resp.session_id, taskId, row.status);
        } catch {
          // task may not be visible yet; realtime events will backfill
        }
      }
      await loadChatSessions();
      return resp;
    },
    [activeSessionId, addActiveTask, loadChatSessions, mode, syncTaskTerminalState, upsertChatResponse, upsertTask]
  );

  const restoreTraceContext = useCallback(
    async (traceId: string) => {
      const bundle = await api.restoreTrace(traceId, activeSessionId ?? undefined);
      const restoredSessionId = String(bundle.session_state?.session_id || "");
      if (restoredSessionId) {
        setActiveSessionId(restoredSessionId);
        recordStateUpdate("activeSessionId");
        const turns = await api.getChatSessionTurns(restoredSessionId);
        hydrateSessionTurns(restoredSessionId, turns);
        setChatTurns(turns);
        recordStateUpdate("chatTurns");
      }
      await loadChatSessions();
      await refreshCore({ silent: true });
      pushToast("Context restored", bundle.summary, bundle.partial_restore ? "default" : "success");
      return bundle;
    },
    [activeSessionId, hydrateSessionTurns, loadChatSessions, pushToast, refreshCore]
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
      coreError,
      tasks,
      datasets,
      runs,
      strategies,
      risk,
      approvals,
      events,
      sseConnectionState,
      activeTasksCount: tasks.filter((item) => !isTaskTerminal(String(item.status ?? ""))).length,
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
      coreError,
      tasks,
      datasets,
      runs,
      strategies,
      risk,
      approvals,
      events,
      sseConnectionState,
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
