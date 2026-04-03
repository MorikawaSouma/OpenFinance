"use client";

import {
  createContext,
  startTransition,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  type ReactNode,
} from "react";

import { useWorkbenchShellActions } from "@/components/providers/workbench-shell-provider";
import {
  useRiskApprovalRealtimeHandlers,
} from "@/components/providers/risk-approval-provider";
import {
  useTaskRealtimeEventHandlers,
} from "@/components/providers/task-realtime-provider";
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
import { classifySseEvent } from "@/lib/realtime/event-normalizer";
import { useWorkbenchChatStore } from "@/lib/workbench-chat-store";
import type { SseEvent } from "@/lib/types";

type RealtimeCoordinatorState = {
  enabled: true;
  ownership: "realtime-coordinator-provider";
  connectionState: "connecting" | "open" | "closed" | "error" | "reconnecting";
  note: string;
};

export type RealtimeCoordinatorConnectionState = RealtimeCoordinatorState["connectionState"];

const RealtimeCoordinatorContext = createContext<RealtimeCoordinatorState | null>(null);
let activeRealtimeSubscriptionOwners = 0;

function eventIdentity(event: SseEvent) {
  const eventId = String(event.event_id ?? "").trim();
  if (eventId) return eventId;
  return [event.type, event.timestamp, event.session_id, event.trace_id].map((row) => String(row ?? "").trim()).join(":");
}

export function RealtimeCoordinatorProvider({ children }: { children: ReactNode }) {
  const { pushToast } = useWorkbenchShellActions();
  const { handleRealtimeTaskEvent } = useTaskRealtimeEventHandlers();
  const { handleRiskEvent, handleApprovalStatusChanged } = useRiskApprovalRealtimeHandlers();
  const prependEvents = useWorkbenchChatStore((state) => state.prependEvents);
  const setSseConnectionState = useWorkbenchChatStore((state) => state.setSseConnectionState);
  const sseConnectionState = useWorkbenchChatStore((state) => state.sseConnectionState);

  const eventBufferRef = useRef<SseEvent[]>([]);
  const eventFlushTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const seenEventOrderRef = useRef<string[]>([]);
  const seenEventIdsRef = useRef<Set<string>>(new Set());

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
    let ownsSubscription = false;
    if (activeRealtimeSubscriptionOwners > 0) {
      // Single-subscriber guard: only one live SSE subscriber may exist for the shared coordinator-owned realtime feed.
      return () => undefined;
    }
    activeRealtimeSubscriptionOwners += 1;
    ownsSubscription = true;

    startTransition(() => {
      setSseConnectionState("connecting");
    });

    const unsubscribe = subscribeEvents({
      onEvent: (event) => {
        const identity = eventIdentity(event);
        if (identity) {
          if (seenEventIdsRef.current.has(identity)) return;
          seenEventIdsRef.current.add(identity);
          seenEventOrderRef.current.push(identity);
          if (seenEventOrderRef.current.length > 500) {
            const oldest = seenEventOrderRef.current.shift();
            if (oldest) {
              seenEventIdsRef.current.delete(oldest);
            }
          }
        }
        enqueueEvent(event);

        const normalized = classifySseEvent(event);
        if (normalized.shouldTouchTasks) {
          handleRealtimeTaskEvent(event);
        }
        if (normalized.domain === "risk") {
          handleRiskEvent(event);
        }
        if (normalized.domain === "approval") {
          handleApprovalStatusChanged(event);
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
      unsubscribe();
      if (eventFlushTimerRef.current) {
        clearTimeout(eventFlushTimerRef.current);
        eventFlushTimerRef.current = null;
      }
      if (ownsSubscription) {
        activeRealtimeSubscriptionOwners = Math.max(0, activeRealtimeSubscriptionOwners - 1);
      }
    };
  }, [
    enqueueEvent,
    handleApprovalStatusChanged,
    handleRealtimeTaskEvent,
    handleRiskEvent,
    pushToast,
    setSseConnectionState,
  ]);

  const value = useMemo<RealtimeCoordinatorState>(
    () => ({
      enabled: true,
      ownership: "realtime-coordinator-provider",
      connectionState: sseConnectionState,
      note: "Global SSE lifecycle stays here; the coordinator dispatches raw events to domain-owned realtime handlers and exposes narrow coordinator-native read surfaces for consumers like /chat.",
    }),
    [sseConnectionState]
  );

  return <RealtimeCoordinatorContext.Provider value={value}>{children}</RealtimeCoordinatorContext.Provider>;
}

export function useRealtimeCoordinator() {
  const ctx = useContext(RealtimeCoordinatorContext);
  if (!ctx) {
    throw new Error("useRealtimeCoordinator must be used within RealtimeCoordinatorProvider");
  }
  return ctx;
}

export function useCoordinatorRawEventFeed() {
  // Narrow coordinator-native raw feed surface for consumers that need the shared event buffer.
  useRealtimeCoordinator();
  return useWorkbenchChatStore((state) => state.events);
}

export function useCoordinatorConnectionState(): RealtimeCoordinatorConnectionState {
  return useRealtimeCoordinator().connectionState;
}
