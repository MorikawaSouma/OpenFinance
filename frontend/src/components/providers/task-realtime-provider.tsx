"use client";

import { useMemo, type ReactNode } from "react";

import { isTaskTerminal, useTaskStore } from "@/lib/task-store";
import type { TaskRecord } from "@/lib/types";

function taskTimestamp(task: TaskRecord): number {
  const updated = Date.parse(String(task.updated_at ?? ""));
  if (Number.isFinite(updated)) return updated;
  const created = Date.parse(String(task.created_at ?? ""));
  if (Number.isFinite(created)) return created;
  return 0;
}

export function TaskRealtimeProvider({ children }: { children: ReactNode }) {
  // Group 1 keeps task writes and task polling on the legacy WorkbenchProvider.
  return <>{children}</>;
}

export function useTaskRealtimeState() {
  const tasksById = useTaskStore((state) => state.tasksById);
  const tasks = useMemo(
    () => Object.values(tasksById).sort((a, b) => taskTimestamp(b) - taskTimestamp(a)),
    [tasksById]
  );
  const activeTasksCount = useMemo(
    () => tasks.filter((task) => !isTaskTerminal(String(task.status ?? ""))).length,
    [tasks]
  );

  return { tasksById, tasks, activeTasksCount };
}

export function useTaskRealtimeActions() {
  return {
    refreshTasks: async () => undefined,
    ensureTaskHydrated: async (_taskId: string) => undefined,
  };
}
