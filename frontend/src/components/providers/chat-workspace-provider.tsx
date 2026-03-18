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

import {
  useResearchContextActions,
  useResearchContextState,
} from "@/components/providers/research-context-provider";
import { useWorkbenchShellState } from "@/components/providers/workbench-shell-provider";
import { useWorkbenchChat } from "@/components/providers/workbench-provider";
import { api } from "@/lib/api";
import { executeChatSend } from "@/lib/chat-runtime";
import { messages } from "@/lib/messages";
import { useRiskApprovalStore } from "@/lib/risk-approval-store";
import { useChatSessionStore, type StoredChatMessage } from "@/lib/chat-session-store";
import { useTaskStore } from "@/lib/task-store";
import { useWorkbenchChatStore } from "@/lib/workbench-chat-store";
import type { ChatResponse, ChatSessionSummary } from "@/lib/types";

export type ChatTraceFilter = "all" | "agent" | "tool" | "artifact" | "audit";
export type ChatTracePanelTab = "live_trace" | "reasoning_steps";
type ChatSessionResolutionSource = "url" | "research_restore" | "persisted" | "server_first" | "none";

type ChatWorkspaceState = {
  routeOwnership: "chat-workspace-provider";
  foundationStatus: "chat-render-owned";
  sessionResolutionSource: ChatSessionResolutionSource;
  routeSessionId: string | null;
  restoredTraceId: string | null;
  activeSessionId: string | null;
  chatSessions: ChatSessionSummary[];
  turns: StoredChatMessage[];
  latestSession: ChatSessionSummary | null;
  planOptions: string[];
  sessionsLoading: boolean;
  turnsLoading: boolean;
  chatRefreshing: boolean;
  chatWorkspaceError: string | null;
  input: string;
  sending: boolean;
  pendingMessage: string;
  eventsOpen: boolean;
  traceFilter: ChatTraceFilter;
  tracePanelTab: ChatTracePanelTab;
  restoreBannerShown: boolean;
  unlockUseCase: string;
  unlockPlanId: string;
  unlockAck: boolean;
};

type ChatWorkspaceActions = {
  refreshSessionList: (options?: {
    preferredSessionId?: string | null;
    skipTurnsReload?: boolean;
    background?: boolean;
  }) => Promise<string | null>;
  refreshActiveSessionTurns: (sessionId?: string | null, options?: { background?: boolean }) => Promise<void>;
  selectSession: (sessionId: string) => Promise<void>;
  sendMessage: (message: string) => Promise<ChatResponse>;
  setRouteContext: (payload: { sessionId?: string | null; restoredTraceId?: string | null }) => void;
  setInput: (next: string) => void;
  setSending: (next: boolean) => void;
  setPendingMessage: (next: string) => void;
  setEventsOpen: (next: boolean) => void;
  setTraceFilter: (next: ChatTraceFilter) => void;
  setTracePanelTab: (next: ChatTracePanelTab) => void;
  setRestoreBannerShown: (next: boolean) => void;
  setUnlockUseCase: (next: string) => void;
  setUnlockPlanId: (next: string) => void;
  setUnlockAck: (next: boolean) => void;
  resetUnlockForm: () => void;
};

const ChatWorkspaceStateContext = createContext<ChatWorkspaceState | null>(null);
const ChatWorkspaceActionsContext = createContext<ChatWorkspaceActions | null>(null);

function normalizeNullableString(value: string | null | undefined): string | null {
  const next = String(value ?? "").trim();
  return next.length > 0 ? next : null;
}

function readRouteContextFromLocation() {
  if (typeof window === "undefined") {
    return {
      routeSessionId: null,
      restoredTraceId: null,
    };
  }
  const params = new URLSearchParams(window.location.search);
  return {
    routeSessionId: normalizeNullableString(params.get("session_id")),
    restoredTraceId: normalizeNullableString(params.get("restored_trace_id")),
  };
}

function isUserSessionId(sessionId: string | null) {
  const normalized = String(sessionId ?? "").trim().toLowerCase();
  if (!normalized) return false;
  return !["workbench", "pipeline", "sse", "global"].includes(normalized);
}

function choosePreferredSessionId(options: {
  preferredSessionId?: string | null;
  currentActiveSessionId?: string | null;
  fallbackSessionId?: string | null;
  rows: ChatSessionSummary[];
}) {
  const candidates = [
    options.preferredSessionId,
    options.currentActiveSessionId,
    options.fallbackSessionId,
    options.rows[0]?.session_id ?? null,
  ].map((value) => normalizeNullableString(value));

  for (const candidate of candidates) {
    if (!candidate) continue;
    if (options.rows.some((row) => row.session_id === candidate)) {
      return candidate;
    }
  }
  return null;
}

function resolveChatBootstrapPriority(options: {
  routeSessionId: string | null;
  routeRestoredTraceId: string | null;
  restoredSessionId: string | null;
  restoredTraceId: string | null;
  persistedSessionId: string | null;
}) {
  // Explicit `/chat` selection priority:
  // URL session_id -> research restore payload -> persisted lastSessionId -> first server session.
  const routeSessionId = normalizeNullableString(options.routeSessionId);
  const routeRestoredTraceId = normalizeNullableString(options.routeRestoredTraceId);
  const restoredSessionId = normalizeNullableString(options.restoredSessionId);
  const restoredTraceId = normalizeNullableString(options.restoredTraceId);
  const persistedSessionId = normalizeNullableString(options.persistedSessionId);

  if (routeSessionId) {
    return {
      preferredSessionId: routeSessionId,
      restoredTraceId: routeRestoredTraceId,
      source: "url" as const,
      shouldConsumeRestorePayload: Boolean(restoredSessionId || restoredTraceId),
    };
  }
  if (routeRestoredTraceId) {
    return {
      preferredSessionId: restoredSessionId ?? persistedSessionId,
      restoredTraceId: routeRestoredTraceId,
      source: "url" as const,
      shouldConsumeRestorePayload: Boolean(restoredSessionId || restoredTraceId),
    };
  }
  if (restoredSessionId || restoredTraceId) {
    return {
      preferredSessionId: restoredSessionId ?? persistedSessionId,
      restoredTraceId,
      source: "research_restore" as const,
      shouldConsumeRestorePayload: true,
    };
  }
  if (persistedSessionId) {
    return {
      preferredSessionId: persistedSessionId,
      restoredTraceId: null,
      source: "persisted" as const,
      shouldConsumeRestorePayload: false,
    };
  }
  return {
    preferredSessionId: null,
    restoredTraceId: null,
    source: "server_first" as const,
    shouldConsumeRestorePayload: false,
  };
}

export function ChatWorkspaceProvider({ children }: { children: ReactNode }) {
  const { lastSessionId, restoredSessionId, restoredTraceId: researchRestoredTraceId } = useResearchContextState();
  const { clearRestoreContext } = useResearchContextActions();
  const { mode } = useWorkbenchShellState();
  const { events, syncActiveSession } = useWorkbenchChat();
  const currentRiskSnapshot = useRiskApprovalStore((state) => state.riskSnapshot);
  const setRiskSnapshot = useRiskApprovalStore((state) => state.setRiskSnapshot);
  const upsertApproval = useRiskApprovalStore((state) => state.upsertApproval);
  const persistedSessions = useChatSessionStore((state) => state.sessions);
  const upsertChatResponse = useChatSessionStore((state) => state.upsertFromResponse);
  const hydrateSessionTurns = useChatSessionStore((state) => state.hydrateSessionTurns);
  const addActiveTask = useTaskStore((state) => state.addActiveTask);
  const upsertTask = useTaskStore((state) => state.upsertTask);
  const syncTaskTerminalState = useTaskStore((state) => state.syncTaskTerminalState);
  const prependEvents = useWorkbenchChatStore((state) => state.prependEvents);

  const [routeSessionId, setRouteSessionId] = useState<string | null>(null);
  const [restoredTraceId, setRestoredTraceId] = useState<string | null>(null);
  const [sessionResolutionSource, setSessionResolutionSource] = useState<ChatSessionResolutionSource>("none");
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [chatSessions, setChatSessions] = useState<ChatSessionSummary[]>([]);
  const [sessionsLoading, setSessionsLoading] = useState(true);
  const [turnsLoading, setTurnsLoading] = useState(false);
  const [chatRefreshPendingCount, setChatRefreshPendingCount] = useState(0);
  const [chatWorkspaceError, setChatWorkspaceError] = useState<string | null>(null);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [pendingMessage, setPendingMessage] = useState("");
  const [eventsOpen, setEventsOpen] = useState(false);
  const [traceFilter, setTraceFilter] = useState<ChatTraceFilter>("all");
  const [tracePanelTab, setTracePanelTab] = useState<ChatTracePanelTab>("live_trace");
  const [restoreBannerShown, setRestoreBannerShown] = useState(false);
  const [unlockUseCase, setUnlockUseCase] = useState("");
  const [unlockPlanId, setUnlockPlanId] = useState("");
  const [unlockAck, setUnlockAck] = useState(false);

  const handledEventIdRef = useRef<string>("");
  const chatRefreshing = chatRefreshPendingCount > 0;
  const turns = useMemo(
    () => (activeSessionId ? persistedSessions[activeSessionId]?.turns ?? [] : []),
    [activeSessionId, persistedSessions]
  );
  const latestSession = useMemo(
    () => chatSessions.find((row) => row.session_id === activeSessionId) ?? chatSessions[0] ?? null,
    [activeSessionId, chatSessions]
  );
  const planOptions = useMemo(() => {
    const rows = new Set<string>();
    for (const session of chatSessions) {
      if (session.last_plan_id && session.last_plan_id.trim().length > 0) {
        rows.add(session.last_plan_id);
      }
    }
    return [...rows];
  }, [chatSessions]);

  const syncWorkspaceActiveSession = useCallback(
    (sessionId: string | null) => {
      const nextSessionId = normalizeNullableString(sessionId);
      setActiveSessionId(nextSessionId);
      syncActiveSession(nextSessionId);
    },
    [syncActiveSession]
  );

  const beginTrackedFreshness = useCallback((background: boolean) => {
    if (!background) {
      return () => undefined;
    }
    setChatRefreshPendingCount((count) => count + 1);
    return () => {
      setChatRefreshPendingCount((count) => Math.max(0, count - 1));
    };
  }, []);

  const refreshActiveSessionTurns = useCallback(
    async (sessionId?: string | null, options?: { background?: boolean }) => {
      const targetSessionId = normalizeNullableString(sessionId ?? activeSessionId);
      if (!targetSessionId) return;
      const background = options?.background ?? false;
      if (!background) {
        setTurnsLoading(true);
      }
      const finishTrackedFreshness = beginTrackedFreshness(background);
      try {
        const rows = await api.getChatSessionTurns(targetSessionId);
        hydrateSessionTurns(targetSessionId, rows);
        setChatWorkspaceError(null);
      } catch (err) {
        setChatWorkspaceError(err instanceof Error ? err.message : messages.toast.unknownError);
      } finally {
        finishTrackedFreshness();
        if (!background) {
          setTurnsLoading(false);
        }
      }
    },
    [activeSessionId, beginTrackedFreshness, hydrateSessionTurns]
  );

  const refreshSessionList = useCallback(
    async (options?: { preferredSessionId?: string | null; skipTurnsReload?: boolean; background?: boolean }) => {
      const background = options?.background ?? false;
      if (!background) {
        setSessionsLoading(true);
      }
      const finishTrackedFreshness = beginTrackedFreshness(background);
      try {
        const rows = await api.getChatSessions();
        setChatSessions(rows);
        const targetSessionId = choosePreferredSessionId({
          preferredSessionId: options?.preferredSessionId ?? routeSessionId,
          currentActiveSessionId: activeSessionId,
          fallbackSessionId: lastSessionId,
          rows,
        });
        if (targetSessionId) {
          syncWorkspaceActiveSession(targetSessionId);
          const cachedTurns = persistedSessions[targetSessionId]?.turns ?? [];
          if (!options?.skipTurnsReload && (cachedTurns.length === 0 || targetSessionId !== activeSessionId)) {
            await refreshActiveSessionTurns(targetSessionId, { background });
          }
        }
        setChatWorkspaceError(null);
        return targetSessionId;
      } catch (err) {
        if (!background) {
          setChatSessions([]);
        }
        setChatWorkspaceError(err instanceof Error ? err.message : messages.toast.unknownError);
        return null;
      } finally {
        finishTrackedFreshness();
        if (!background) {
          setSessionsLoading(false);
        }
      }
    },
    [
      activeSessionId,
      beginTrackedFreshness,
      lastSessionId,
      persistedSessions,
      refreshActiveSessionTurns,
      routeSessionId,
      syncWorkspaceActiveSession,
    ]
  );

  const selectSession = useCallback(
    async (sessionId: string) => {
      const targetSessionId = normalizeNullableString(sessionId);
      if (!targetSessionId) return;
      syncWorkspaceActiveSession(targetSessionId);
      setChatWorkspaceError(null);
      const cachedTurns = persistedSessions[targetSessionId]?.turns ?? [];
      if (cachedTurns.length === 0) {
        await refreshActiveSessionTurns(targetSessionId);
        return;
      }
      void refreshActiveSessionTurns(targetSessionId, { background: true });
    },
    [persistedSessions, refreshActiveSessionTurns, syncWorkspaceActiveSession]
  );

  const reconcileChatFreshness = useCallback(
    async (options?: { preferredSessionId?: string | null; forceTurnsRefresh?: boolean; skipTurnsReload?: boolean }) => {
      const targetSessionId =
        (await refreshSessionList({
          preferredSessionId: options?.preferredSessionId,
          skipTurnsReload: options?.skipTurnsReload,
          background: true,
        })) ?? normalizeNullableString(options?.preferredSessionId ?? activeSessionId);

      if (options?.forceTurnsRefresh && targetSessionId) {
        await refreshActiveSessionTurns(targetSessionId, { background: true });
      }

      return targetSessionId;
    },
    [activeSessionId, refreshActiveSessionTurns, refreshSessionList]
  );

  const sendMessage = useCallback(
    async (message: string) => {
      const trimmed = message.trim();
      if (!trimmed) {
        throw new Error(messages.chat.askPlaceholder);
      }
      if (sending) {
        throw new Error(messages.chat.running);
      }

      const sessionIdForRequest = activeSessionId ?? routeSessionId ?? lastSessionId ?? null;
      if (sessionIdForRequest) {
        syncWorkspaceActiveSession(sessionIdForRequest);
      }

      setSending(true);
      setPendingMessage(trimmed);
      try {
        const response = await executeChatSend({
          message: trimmed,
          sessionIdForRequest,
          includeDebug: mode === "developer",
          currentRiskSnapshot,
          syncActiveSession: syncWorkspaceActiveSession,
          upsertChatResponse,
          setRiskSnapshot,
          upsertApproval,
          prependEvents,
          addActiveTask,
          upsertTask,
          syncTaskTerminalState,
        });
        const nextSessionId = normalizeNullableString(response.session_id);
        setInput("");
        await reconcileChatFreshness({
          preferredSessionId: nextSessionId,
          skipTurnsReload: Array.isArray(response.turns) && response.turns.length > 0,
          forceTurnsRefresh: !Array.isArray(response.turns) || response.turns.length === 0,
        });
        setChatWorkspaceError(null);
        return response;
      } finally {
        setSending(false);
        setPendingMessage("");
      }
    },
    [
      activeSessionId,
      addActiveTask,
      currentRiskSnapshot,
      lastSessionId,
      mode,
      prependEvents,
      reconcileChatFreshness,
      routeSessionId,
      sending,
      setRiskSnapshot,
      syncWorkspaceActiveSession,
      syncTaskTerminalState,
      upsertApproval,
      upsertChatResponse,
      upsertTask,
    ]
  );

  useEffect(() => {
    const routeContext = readRouteContextFromLocation();
    const resolved = resolveChatBootstrapPriority({
      routeSessionId: routeContext.routeSessionId,
      routeRestoredTraceId: routeContext.restoredTraceId,
      restoredSessionId,
      restoredTraceId: researchRestoredTraceId,
      persistedSessionId: lastSessionId,
    });
    setRouteSessionId(routeContext.routeSessionId);
    setRestoredTraceId(resolved.restoredTraceId);
    setSessionResolutionSource(resolved.source);
    void refreshSessionList({
      preferredSessionId: resolved.preferredSessionId,
    });
    if (resolved.shouldConsumeRestorePayload) {
      clearRestoreContext();
    }
    // Initialize the route-local chat workspace once. Subsequent freshness comes from explicit actions and legacy event feed.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const latestEvent = events[0];
    const eventId = String(latestEvent?.event_id ?? "").trim();
    if (!eventId || eventId === handledEventIdRef.current) return;
    handledEventIdRef.current = eventId;

    const eventSessionId = normalizeNullableString(String(latestEvent?.session_id ?? ""));
    if (!isUserSessionId(eventSessionId)) return;

    const type = String(latestEvent?.type ?? "").toLowerCase();
    if (eventSessionId && activeSessionId && eventSessionId === activeSessionId) {
      if (type === "chat.done" || type === "task.done" || type === "task.error") {
        void refreshActiveSessionTurns(eventSessionId, { background: true });
      }
    }
    if (type === "chat.done" || type === "task.done" || type === "task.error") {
      void reconcileChatFreshness({
        preferredSessionId: activeSessionId,
        skipTurnsReload: true,
      });
    }
  }, [activeSessionId, events, reconcileChatFreshness, refreshActiveSessionTurns]);

  const state = useMemo<ChatWorkspaceState>(
    () => ({
      routeOwnership: "chat-workspace-provider",
      foundationStatus: "chat-render-owned",
      sessionResolutionSource,
      routeSessionId,
      restoredTraceId,
      activeSessionId,
      chatSessions,
      turns,
      latestSession,
      planOptions,
      sessionsLoading,
      turnsLoading,
      chatRefreshing,
      chatWorkspaceError,
      input,
      sending,
      pendingMessage,
      eventsOpen,
      traceFilter,
      tracePanelTab,
      restoreBannerShown,
      unlockUseCase,
      unlockPlanId,
      unlockAck,
    }),
    [
      activeSessionId,
      chatSessions,
      chatRefreshing,
      chatWorkspaceError,
      eventsOpen,
      input,
      latestSession,
      pendingMessage,
      planOptions,
      restoreBannerShown,
      restoredTraceId,
      routeSessionId,
      sessionResolutionSource,
      sending,
      sessionsLoading,
      traceFilter,
      tracePanelTab,
      turns,
      turnsLoading,
      unlockAck,
      unlockPlanId,
      unlockUseCase,
    ]
  );

  const actions = useMemo<ChatWorkspaceActions>(
    () => ({
      refreshSessionList,
      refreshActiveSessionTurns,
      selectSession,
      sendMessage,
      setRouteContext: (payload) => {
        setRouteSessionId(normalizeNullableString(payload.sessionId));
        setRestoredTraceId(normalizeNullableString(payload.restoredTraceId));
      },
      setInput,
      setSending,
      setPendingMessage,
      setEventsOpen,
      setTraceFilter,
      setTracePanelTab,
      setRestoreBannerShown,
      setUnlockUseCase,
      setUnlockPlanId,
      setUnlockAck,
      resetUnlockForm: () => {
        setUnlockUseCase("");
        setUnlockPlanId("");
        setUnlockAck(false);
      },
    }),
    [refreshActiveSessionTurns, refreshSessionList, selectSession, sendMessage]
  );

  return (
    <ChatWorkspaceStateContext.Provider value={state}>
      <ChatWorkspaceActionsContext.Provider value={actions}>{children}</ChatWorkspaceActionsContext.Provider>
    </ChatWorkspaceStateContext.Provider>
  );
}

export function useChatWorkspaceState() {
  const ctx = useContext(ChatWorkspaceStateContext);
  if (!ctx) {
    throw new Error("useChatWorkspaceState must be used within ChatWorkspaceProvider");
  }
  return ctx;
}

export function useChatWorkspaceActions() {
  const ctx = useContext(ChatWorkspaceActionsContext);
  if (!ctx) {
    throw new Error("useChatWorkspaceActions must be used within ChatWorkspaceProvider");
  }
  return ctx;
}

export function useChatWorkspaceLegacyBridge() {
  // Explicit transitional bridge: global SSE/event feed buffering remains legacy-backed after chat restore/freshness ownership moves.
  const workbenchChat = useWorkbenchChat();

  return {
    bridgeOwnership: "legacy-workbench-provider" as const,
    bridgeStatus: "required-for-global-chat-events" as const,
    events: workbenchChat.events,
    sseConnectionState: workbenchChat.sseConnectionState,
  };
}
