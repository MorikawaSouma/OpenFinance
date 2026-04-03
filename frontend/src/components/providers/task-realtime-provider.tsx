"use client";

import { useCallback, useEffect, useMemo, useRef, type ReactNode } from "react";

import { api } from "@/lib/api";
import { recordStateUpdate } from "@/lib/debug";
import { messages } from "@/lib/messages";
import { isTaskTerminal, useTaskStore } from "@/lib/task-store";
import { useWorkbenchChatStore } from "@/lib/workbench-chat-store";
import type { SseEvent, TaskRecord } from "@/lib/types";

const NON_USER_SESSION_SCOPES = new Set(["workbench", "pipeline", "sse", "global"]);
const ACTIVE_TASK_FALLBACK_POLL_MS = 4_000;
let taskListRefreshInFlight: Promise<void> | null = null;
const taskHydrationInFlight = new Map<string, Promise<TaskRecord | null>>();

function taskTimestamp(task: TaskRecord): number {
  const updated = Date.parse(String(task.updated_at ?? ""));
  if (Number.isFinite(updated)) return updated;
  const created = Date.parse(String(task.created_at ?? ""));
  if (Number.isFinite(created)) return created;
  return 0;
}

function toObject(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : {};
}

export function TaskRealtimeProvider({ children }: { children: ReactNode }) {
  const sseConnectionState = useWorkbenchChatStore((state) => state.sseConnectionState);
  const tasksById = useTaskStore((state) => state.tasksById);
  const activeTaskIdsBySession = useTaskStore((state) => state.activeTaskIdsBySession);
  const lastTaskListRefreshAt = useTaskStore((state) => state.lastTaskListRefreshAt);
  const taskListRefreshing = useTaskStore((state) => state.taskListRefreshing);
  const taskListError = useTaskStore((state) => state.taskListError);
  const { ensureTaskHydrated, refreshTasks } = useTaskRealtimeActions();
  const activeTaskIds = useMemo(
    () =>
      Array.from(
        new Set(
          Object.values(activeTaskIdsBySession)
            .flatMap((rows) => rows)
            .map((taskId) => String(taskId ?? "").trim())
            .filter(Boolean)
        )
      ),
    [activeTaskIdsBySession]
  );
  const activeNonTerminalTaskIds = useMemo(
    () =>
      activeTaskIds.filter((taskId) => {
        const task = tasksById[taskId];
        if (!task) return true;
        return !isTaskTerminal(String(task.status ?? ""));
      }),
    [activeTaskIds, tasksById]
  );
  const didBootstrapActiveHydrateRef = useRef(false);
  const previousSseConnectionStateRef = useRef<string | null>(null);

  const hydrateActiveTasks = useCallback(
    async (taskIds: string[]) => {
      const normalizedIds = taskIds.map((taskId) => String(taskId ?? "").trim()).filter(Boolean);
      if (normalizedIds.length === 0) return;
      await Promise.all(
        normalizedIds.map((taskId) =>
          ensureTaskHydrated(taskId).catch(() => null)
        )
      );
      recordStateUpdate("tasks");
    },
    [ensureTaskHydrated]
  );

  useEffect(() => {
    if (lastTaskListRefreshAt !== null || taskListRefreshing || taskListError) return;
    void refreshTasks().catch(() => undefined);
  }, [lastTaskListRefreshAt, refreshTasks, taskListError, taskListRefreshing]);

  useEffect(() => {
    if (didBootstrapActiveHydrateRef.current) return;
    if (activeTaskIds.length === 0) return;
    didBootstrapActiveHydrateRef.current = true;
    void hydrateActiveTasks(activeTaskIds);
  }, [activeTaskIds, hydrateActiveTasks]);

  useEffect(() => {
    const previous = previousSseConnectionStateRef.current;
    previousSseConnectionStateRef.current = sseConnectionState;
    if (sseConnectionState === "open" && previous && previous !== "open") {
      void hydrateActiveTasks(activeTaskIds);
    }
  }, [activeTaskIds, hydrateActiveTasks, sseConnectionState]);

  useEffect(() => {
    if (sseConnectionState === "open") return;
    if (activeNonTerminalTaskIds.length === 0) return;

    const timer = setInterval(() => {
      void hydrateActiveTasks(activeNonTerminalTaskIds);
    }, ACTIVE_TASK_FALLBACK_POLL_MS);

    return () => {
      clearInterval(timer);
    };
  }, [activeNonTerminalTaskIds, hydrateActiveTasks, sseConnectionState]);

  return <>{children}</>;
}

export function useTaskRealtimeState() {
  const tasksById = useTaskStore((state) => state.tasksById);
  const lastTaskListRefreshAt = useTaskStore((state) => state.lastTaskListRefreshAt);
  const taskListRefreshing = useTaskStore((state) => state.taskListRefreshing);
  const taskListError = useTaskStore((state) => state.taskListError);
  const tasks = useMemo(
    () => Object.values(tasksById).sort((a, b) => taskTimestamp(b) - taskTimestamp(a)),
    [tasksById]
  );
  const activeTasksCount = useMemo(
    () => tasks.filter((task) => !isTaskTerminal(String(task.status ?? ""))).length,
    [tasks]
  );
  const hasTaskListLoaded = useMemo(
    () => lastTaskListRefreshAt !== null,
    [lastTaskListRefreshAt]
  );
  const isTaskListBootstrapPending = useMemo(
    () => !hasTaskListLoaded && tasks.length === 0 && !taskListError,
    [hasTaskListLoaded, taskListError, tasks.length]
  );

  return {
    tasksById,
    tasks,
    activeTasksCount,
    lastTaskListRefreshAt,
    hasTaskListLoaded,
    isTaskListBootstrapPending,
    taskListRefreshing,
    taskListError,
  };
}

export function useTaskRealtimeActions() {
  const reconcileTasks = useTaskStore((state) => state.reconcileTasks);
  const upsertTask = useTaskStore((state) => state.upsertTask);
  const addActiveTask = useTaskStore((state) => state.addActiveTask);
  const syncTaskTerminalState = useTaskStore((state) => state.syncTaskTerminalState);
  const setTaskListRefreshing = useTaskStore((state) => state.setTaskListRefreshing);
  const setTaskListError = useTaskStore((state) => state.setTaskListError);

  const refreshTasks = useCallback(async () => {
    if (taskListRefreshInFlight) {
      return taskListRefreshInFlight;
    }

    const refreshPromise = (async () => {
      setTaskListRefreshing(true);
      setTaskListError(null);
      try {
        const rows = await api.getTasks();
        reconcileTasks(rows);
        for (const row of rows) {
          const sessionId = String((row.meta as Record<string, unknown> | undefined)?.session_id ?? "").trim();
          if (!sessionId) continue;
          addActiveTask(sessionId, row.task_id);
          syncTaskTerminalState(sessionId, row.task_id, row.status);
        }
        recordStateUpdate("tasks");
      } catch (err) {
        setTaskListError(err instanceof Error ? err.message : messages.toast.unknownError);
        throw err;
      } finally {
        setTaskListRefreshing(false);
      }
    })();

    taskListRefreshInFlight = refreshPromise;
    try {
      await refreshPromise;
    } finally {
      if (taskListRefreshInFlight === refreshPromise) {
        taskListRefreshInFlight = null;
      }
    }
  }, [addActiveTask, reconcileTasks, setTaskListError, setTaskListRefreshing, syncTaskTerminalState]);

  const ensureTaskHydrated = useCallback(
    async (taskId: string) => {
      const normalizedTaskId = String(taskId ?? "").trim();
      if (!normalizedTaskId) return null;

      const existing = taskHydrationInFlight.get(normalizedTaskId);
      if (existing) {
        return existing;
      }

      const hydratePromise = (async () => {
        const row = await api.getTask(normalizedTaskId);
        upsertTask(row);
        const sessionId = String((row.meta as Record<string, unknown> | undefined)?.session_id ?? "").trim();
        if (sessionId) {
          addActiveTask(sessionId, row.task_id);
          syncTaskTerminalState(sessionId, row.task_id, row.status);
        }
        recordStateUpdate("tasks");
        return row;
      })();

      taskHydrationInFlight.set(normalizedTaskId, hydratePromise);
      try {
        return await hydratePromise;
      } finally {
        if (taskHydrationInFlight.get(normalizedTaskId) === hydratePromise) {
          taskHydrationInFlight.delete(normalizedTaskId);
        }
      }
    },
    [addActiveTask, syncTaskTerminalState, upsertTask]
  );

  return useMemo(
    () => ({
      refreshTasks,
      ensureTaskHydrated,
    }),
    [ensureTaskHydrated, refreshTasks]
  );
}

export function useTaskRealtimeEventHandlers() {
  const upsertTask = useTaskStore((state) => state.upsertTask);
  const addActiveTask = useTaskStore((state) => state.addActiveTask);
  const syncTaskTerminalState = useTaskStore((state) => state.syncTaskTerminalState);
  const getTask = useTaskStore((state) => state.getTask);

  const handleRealtimeTaskEvent = useCallback(
    (event: SseEvent) => {
      const type = String(event.type ?? "").trim().toLowerCase();
      if (!["task.created", "task.progress", "task.heartbeat", "task.done", "task.error"].includes(type)) {
        return;
      }

      const payload = toObject(event.payload);
      const rawTask = toObject(payload.task);
      const source = Object.keys(rawTask).length > 0 ? rawTask : payload;
      const taskId = String(source.task_id ?? payload.task_id ?? "").trim();
      if (!taskId) return;
      const previousTask = getTask(taskId);

      const parentTaskId = String(source.parent_task_id ?? payload.parent_task_id ?? "").trim();
      const nextResult = "result" in source ? toObject(source.result) : previousTask?.result ?? {};
      const nextResultRef = "result_ref" in source ? toObject(source.result_ref) : previousTask?.result_ref ?? {};
      const nextMeta = "meta" in source ? toObject(source.meta) : previousTask?.meta ?? {};
      const nextMessage =
        "message" in source
          ? String(source.message ?? "")
          : "message" in payload
            ? String(payload.message ?? "")
            : String(previousTask?.message ?? "");
      const nextError =
        "error" in source
          ? (source.error ? String(source.error) : null)
          : previousTask?.error ?? null;
      const nextTask: TaskRecord = {
        task_id: taskId,
        parent_task_id: parentTaskId || previousTask?.parent_task_id || undefined,
        task_type: String(source.task_type ?? source.type ?? payload.type ?? previousTask?.task_type ?? "task"),
        status: String(source.status ?? payload.status ?? previousTask?.status ?? "running"),
        progress: Number(source.progress ?? payload.progress ?? previousTask?.progress ?? 0),
        message: nextMessage,
        result: nextResult,
        result_ref: nextResultRef,
        meta: nextMeta,
        created_at: String(source.created_at ?? previousTask?.created_at ?? ""),
        updated_at: String(source.updated_at ?? previousTask?.updated_at ?? ""),
        error: nextError,
      };

      upsertTask(nextTask);

      const sessionId = String(event.session_id ?? source.session_id ?? nextTask.meta?.session_id ?? "").trim();
      if (sessionId && !NON_USER_SESSION_SCOPES.has(sessionId.toLowerCase())) {
        addActiveTask(sessionId, taskId);
        if (isTaskTerminal(nextTask.status)) {
          syncTaskTerminalState(sessionId, taskId, nextTask.status);
        }
      }

      recordStateUpdate("tasks");
    },
    [addActiveTask, getTask, syncTaskTerminalState, upsertTask]
  );

  return useMemo(
    () => ({
      handleRealtimeTaskEvent,
    }),
    [handleRealtimeTaskEvent]
  );
}
