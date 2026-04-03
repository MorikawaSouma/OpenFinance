"use client";

import { create } from "zustand";
import { createJSONStorage, persist } from "zustand/middleware";

import type { TaskRecord } from "@/lib/types";

const MAX_PERSISTED_TASKS = 400;

function toObject(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : {};
}

function timestampValue(task: TaskRecord): number {
  const updated = Date.parse(String(task.updated_at ?? ""));
  if (Number.isFinite(updated)) return updated;
  const created = Date.parse(String(task.created_at ?? ""));
  if (Number.isFinite(created)) return created;
  return 0;
}

function normalizeTask(input: TaskRecord): TaskRecord {
  return {
    task_id: String(input.task_id ?? "").trim(),
    parent_task_id: input.parent_task_id ? String(input.parent_task_id).trim() : undefined,
    task_type: String(input.task_type ?? "task"),
    status: String(input.status ?? "queued"),
    progress: Number.isFinite(Number(input.progress)) ? Number(input.progress) : 0,
    message: String(input.message ?? ""),
    result: toObject(input.result),
    result_ref: toObject(input.result_ref),
    meta: toObject(input.meta),
    created_at: input.created_at ? String(input.created_at) : "",
    updated_at: input.updated_at ? String(input.updated_at) : "",
    error: input.error ? String(input.error) : null,
  };
}

function mergeTask(prev: TaskRecord | undefined, next: TaskRecord): TaskRecord {
  if (!prev) return normalizeTask(next);
  const normalized = normalizeTask(next);
  return {
    ...prev,
    ...normalized,
    result: { ...toObject(prev.result), ...toObject(normalized.result) },
    result_ref: { ...toObject(prev.result_ref), ...toObject(normalized.result_ref) },
    meta: { ...toObject(prev.meta), ...toObject(normalized.meta) },
  };
}

function trimTaskMap(tasksById: Record<string, TaskRecord>): Record<string, TaskRecord> {
  const entries = Object.entries(tasksById);
  if (entries.length <= MAX_PERSISTED_TASKS) return tasksById;
  entries.sort((a, b) => timestampValue(b[1]) - timestampValue(a[1]));
  const trimmed = entries.slice(0, MAX_PERSISTED_TASKS);
  return Object.fromEntries(trimmed);
}

function sortedTasks(tasksById: Record<string, TaskRecord>): TaskRecord[] {
  return Object.values(tasksById).sort((a, b) => timestampValue(b) - timestampValue(a));
}

function uniqueTaskIds(ids: string[]): string[] {
  const out: string[] = [];
  const seen = new Set<string>();
  for (const raw of ids) {
    const taskId = String(raw ?? "").trim();
    if (!taskId || seen.has(taskId)) continue;
    seen.add(taskId);
    out.push(taskId);
  }
  return out;
}

function isTerminal(status: string): boolean {
  const value = status.toLowerCase();
  return value === "done" || value === "error" || value === "failed" || value === "canceled";
}

type TaskStoreState = {
  tasksById: Record<string, TaskRecord>;
  activeTaskIdsBySession: Record<string, string[]>;
  lastTaskListRefreshAt: string | null;
  taskListRefreshing: boolean;
  taskListError: string | null;
  replaceTasks: (tasks: TaskRecord[]) => void;
  reconcileTasks: (tasks: TaskRecord[]) => void;
  upsertTask: (task: TaskRecord) => void;
  getTask: (taskId: string) => TaskRecord | undefined;
  listTasks: () => TaskRecord[];
  addActiveTask: (sessionId: string, taskId: string) => void;
  removeActiveTask: (sessionId: string, taskId: string) => void;
  listActiveTaskIds: (sessionId: string) => string[];
  listAllActiveTaskIds: () => string[];
  syncTaskTerminalState: (sessionId: string, taskId: string, status: string) => void;
  setTaskListRefreshing: (next: boolean) => void;
  setTaskListError: (message: string | null) => void;
};

export const useTaskStore = create<TaskStoreState>()(
  persist(
    (set, get) => ({
      tasksById: {},
      activeTaskIdsBySession: {},
      lastTaskListRefreshAt: null,
      taskListRefreshing: false,
      taskListError: null,

      replaceTasks: (tasks: TaskRecord[]) => {
        const nextMap: Record<string, TaskRecord> = {};
        for (const row of tasks) {
          const taskId = String(row.task_id ?? "").trim();
          if (!taskId) continue;
          nextMap[taskId] = normalizeTask(row);
        }
        set({
          tasksById: trimTaskMap(nextMap),
          lastTaskListRefreshAt: new Date().toISOString(),
          taskListError: null,
        });
      },

      reconcileTasks: (tasks: TaskRecord[]) => {
        const nextMap = { ...get().tasksById };
        for (const row of tasks) {
          const taskId = String(row.task_id ?? "").trim();
          if (!taskId) continue;
          nextMap[taskId] = mergeTask(nextMap[taskId], row);
        }
        set({
          tasksById: trimTaskMap(nextMap),
          lastTaskListRefreshAt: new Date().toISOString(),
          taskListError: null,
        });
      },

      upsertTask: (task: TaskRecord) => {
        const taskId = String(task.task_id ?? "").trim();
        if (!taskId) return;
        const nextMap = { ...get().tasksById };
        nextMap[taskId] = mergeTask(nextMap[taskId], task);
        set({ tasksById: trimTaskMap(nextMap) });
      },

      getTask: (taskId: string) => {
        const key = String(taskId ?? "").trim();
        if (!key) return undefined;
        return get().tasksById[key];
      },

      listTasks: () => sortedTasks(get().tasksById),

      addActiveTask: (sessionId: string, taskId: string) => {
        const sid = String(sessionId ?? "").trim();
        const tid = String(taskId ?? "").trim();
        if (!sid || !tid) return;
        const next = { ...get().activeTaskIdsBySession };
        const current = next[sid] ?? [];
        next[sid] = uniqueTaskIds([tid, ...current]).slice(0, 32);
        set({ activeTaskIdsBySession: next });
      },

      removeActiveTask: (sessionId: string, taskId: string) => {
        const sid = String(sessionId ?? "").trim();
        const tid = String(taskId ?? "").trim();
        if (!sid || !tid) return;
        const next = { ...get().activeTaskIdsBySession };
        const current = (next[sid] ?? []).filter((row) => row !== tid);
        if (current.length === 0) {
          delete next[sid];
        } else {
          next[sid] = current;
        }
        set({ activeTaskIdsBySession: next });
      },

      listActiveTaskIds: (sessionId: string) => {
        const sid = String(sessionId ?? "").trim();
        if (!sid) return [];
        return [...(get().activeTaskIdsBySession[sid] ?? [])];
      },

      listAllActiveTaskIds: () => {
        const out: string[] = [];
        for (const ids of Object.values(get().activeTaskIdsBySession)) {
          out.push(...ids);
        }
        return uniqueTaskIds(out);
      },

      syncTaskTerminalState: (sessionId: string, taskId: string, status: string) => {
        if (!isTerminal(String(status ?? ""))) return;
        get().removeActiveTask(sessionId, taskId);
      },

      setTaskListRefreshing: (next) => {
        set({ taskListRefreshing: next });
      },

      setTaskListError: (message) => {
        set({ taskListError: message });
      },
    }),
    {
      name: "of-task-store",
      storage: createJSONStorage(() => localStorage),
      partialize: (state) => ({
        tasksById: state.tasksById,
        activeTaskIdsBySession: state.activeTaskIdsBySession,
      }),
    }
  )
);

export function isTaskTerminal(status: string): boolean {
  return isTerminal(status);
}
