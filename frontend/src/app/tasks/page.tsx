"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { EmptyState } from "@/components/common/empty-state";
import { useResearchContextState } from "@/components/providers/research-context-provider";
import { useTaskRealtimeState } from "@/components/providers/task-realtime-provider";
import { useWorkbench } from "@/components/providers/workbench-provider";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import type { TaskRecord } from "@/lib/types";

function statusVariant(status: string): "success" | "destructive" | "warning" | "muted" {
  const value = String(status).toLowerCase();
  if (value === "done") return "success";
  if (value === "error" || value === "failed") return "destructive";
  if (value === "running") return "warning";
  return "muted";
}

function tsValue(task: TaskRecord) {
  return String(task.updated_at ?? task.created_at ?? "");
}

function progressValue(value: unknown) {
  if (typeof value !== "number" || Number.isNaN(value)) return 0;
  return Math.max(0, Math.min(100, value));
}

function stageLabel(stage: string) {
  const key = String(stage || "").trim().toLowerCase();
  const map: Record<string, string> = {
    "pipeline.start": "Initializing",
    "plan.compose": "Composing plan",
    "agent.reasoning": "Agent reasoning",
    "evidence.pack": "Packing evidence",
    "dataset.prepare": "Preparing dataset",
    "variant.factor": "Computing factor",
    "variant.strategy": "Selecting strategy",
    "variant.backtest": "Running backtest",
    "variants.running": "Running variants",
    "backtest.compare": "Comparing variants",
    "paper.trade": "Paper trading",
    "pipeline.done": "Finalizing report",
  };
  return map[key] ?? "Running";
}

function elapsedLabel(ms: unknown) {
  const numeric = Number(ms ?? 0);
  if (!Number.isFinite(numeric) || numeric <= 0) return "";
  return `${Math.floor(numeric / 1000)}s`;
}

function runReportLink(task: TaskRecord) {
  const runFromRef = String(task.result_ref?.run_id ?? "").trim();
  if (runFromRef) return `/reports/${runFromRef}`;
  const runFromResult = String(task.result?.run_id ?? "").trim();
  if (runFromResult) return `/reports/${runFromResult}`;
  const openPath = String(task.result_ref?.open_path ?? "").trim();
  if (openPath) return openPath;
  return "";
}

function compareLink(task: TaskRecord) {
  const openPath = String(task.result_ref?.open_path ?? "").trim();
  if (openPath) return openPath;
  const comparePath = String(task.result_ref?.compare_path ?? "").trim();
  if (comparePath) return comparePath;
  return "";
}

function planLink(task: TaskRecord) {
  const id = String(task.result_ref?.plan_id ?? task.result?.plan_id ?? "").trim();
  return id ? `/plan/${id}` : "";
}

function evidenceLink(task: TaskRecord) {
  const summary = (task.result?.summary ?? {}) as Record<string, unknown>;
  const id = String(task.result_ref?.evidence_pack_id ?? summary.evidence_pack_id ?? "").trim();
  return id ? "/evidence" : "";
}

export default function TasksPage() {
  const { loadingCore, coreError, refreshCore } = useWorkbench();
  const { lastSessionId } = useResearchContextState();
  const { tasks } = useTaskRealtimeState();
  const [focusTaskId, setFocusTaskId] = useState("");

  useEffect(() => {
    if (typeof window === "undefined") return;
    const value = String(new URLSearchParams(window.location.search).get("focus_task_id") ?? "").trim();
    setFocusTaskId(value);
  }, []);

  const sessionScopedTasks = useMemo(() => {
    const sid = String(lastSessionId ?? "").trim();
    if (!sid) return tasks;
    const direct = tasks.filter((task) => String((task.meta ?? {}).session_id ?? "").trim() === sid);
    if (direct.length === 0) return tasks;
    const byId = new Map(tasks.map((task) => [String(task.task_id), task]));
    const selected = new Set<string>(direct.map((task) => String(task.task_id)));
    const queue = [...selected];
    while (queue.length > 0) {
      const current = queue.pop() ?? "";
      const currentTask = byId.get(current);
      const parentId = String(currentTask?.parent_task_id ?? "").trim();
      if (parentId && !selected.has(parentId)) {
        selected.add(parentId);
        queue.push(parentId);
      }
      for (const task of tasks) {
        if (String(task.parent_task_id ?? "").trim() === current) {
          const taskId = String(task.task_id);
          if (!selected.has(taskId)) {
            selected.add(taskId);
            queue.push(taskId);
          }
        }
      }
    }
    return tasks.filter((task) => selected.has(String(task.task_id)));
  }, [lastSessionId, tasks]);

  const { parents, childrenByParent } = useMemo(() => {
    const map = new Map<string, TaskRecord>();
    for (const task of sessionScopedTasks) {
      map.set(String(task.task_id), task);
    }
    const childMap = new Map<string, TaskRecord[]>();
    const parentRows: TaskRecord[] = [];
    for (const task of sessionScopedTasks) {
      const parentId = String(task.parent_task_id ?? "").trim();
      if (!parentId || !map.has(parentId)) {
        parentRows.push(task);
        continue;
      }
      const rows = childMap.get(parentId) ?? [];
      rows.push(task);
      childMap.set(parentId, rows);
    }
    parentRows.sort((a, b) => (tsValue(a) < tsValue(b) ? 1 : -1));
    for (const [key, rows] of childMap.entries()) {
      rows.sort((a, b) => (tsValue(a) < tsValue(b) ? 1 : -1));
      childMap.set(key, rows);
    }
    return { parents: parentRows, childrenByParent: childMap };
  }, [sessionScopedTasks]);

  return (
    <Card>
      <CardHeader>
        <CardTitle>Tasks</CardTitle>
      </CardHeader>
      <CardContent>
        {loadingCore ? (
          <div className="space-y-2">
            {Array.from({ length: 8 }).map((_, i) => (
              <Skeleton key={i} className="h-12 w-full" />
            ))}
          </div>
        ) : coreError && sessionScopedTasks.length === 0 ? (
          <div className="rounded-lg border border-destructive/40 bg-destructive/5 p-4">
            <p className="text-sm font-semibold text-destructive">Failed to load tasks</p>
            <p className="mt-1 text-xs text-muted-foreground">{coreError}</p>
            <Button className="mt-3" size="sm" variant="outline" onClick={() => void refreshCore()}>
              Retry
            </Button>
          </div>
        ) : sessionScopedTasks.length === 0 ? (
          <EmptyState title="No tasks yet" description="Generate data or run a backtest to populate this list." />
        ) : (
          <div className="space-y-3">
            {parents.map((task) => {
              const childRows = childrenByParent.get(String(task.task_id)) ?? [];
              const doneCount = childRows.filter((row) => String(row.status).toLowerCase() === "done").length;
              const focused = focusTaskId && String(task.task_id) === focusTaskId;
              const parentReportLink = compareLink(task);
              const parentPlanLink = planLink(task);
              const parentEvidenceLink = evidenceLink(task);
              const parentMeta = (task.meta ?? {}) as Record<string, unknown>;
              const parentSummary = (task.result?.summary ?? {}) as Record<string, unknown>;
              const parentStage = stageLabel(String(parentMeta.last_stage ?? ""));
              const parentElapsed = elapsedLabel(parentMeta.last_elapsed_ms);
              const parentStatusText = String(parentMeta.status_text ?? "").trim();
              const reasoningStepCount = Number(
                parentSummary.reasoning_step_count ??
                  (Array.isArray(task.result?.reasoning_steps) ? task.result.reasoning_steps.length : 0)
              );
              return (
                <details key={task.task_id} open={focused || childRows.length > 0} className={`rounded-xl border border-border p-3 ${focused ? "ring-2 ring-primary/40" : ""}`}>
                  <summary className="cursor-pointer list-none">
                    <div className="flex items-center justify-between gap-3">
                      <div className="min-w-0">
                        <p className="truncate text-sm font-semibold">{task.task_type}</p>
                        <p className="mt-1 text-xs text-muted-foreground">{task.message || "Task running..."}</p>
                      </div>
                      <Badge variant={statusVariant(task.status)}>{task.status}</Badge>
                    </div>
                    <div className="mt-2">
                      <div className="h-1.5 w-full rounded bg-muted/40">
                        <div className="h-1.5 rounded bg-primary transition-all" style={{ width: `${progressValue(task.progress)}%` }} />
                      </div>
                      <div className="mt-1 flex items-center justify-between text-[11px] text-muted-foreground">
                        <span>{progressValue(task.progress)}%</span>
                        {childRows.length > 0 ? <span>{doneCount}/{childRows.length} variants completed</span> : null}
                      </div>
                    </div>
                    <div className="mt-2 flex flex-wrap gap-3 text-xs">
                      <span className="text-muted-foreground">
                        {`stage: ${parentStage}${parentElapsed ? ` (${parentElapsed})` : ""}${parentStatusText ? ` · ${parentStatusText}` : ""}`}
                      </span>
                      {parentReportLink ? (
                        <Link href={parentReportLink} className="text-primary underline">
                          Open Compare
                        </Link>
                      ) : null}
                      {parentPlanLink ? (
                        <Link href={parentPlanLink} className="text-primary underline">
                          Open Plan
                        </Link>
                      ) : null}
                      {parentEvidenceLink ? (
                        <Link href={parentEvidenceLink} className="text-primary underline">
                          Open Evidence
                        </Link>
                      ) : null}
                      {Number.isFinite(reasoningStepCount) && reasoningStepCount > 0 ? (
                        <span className="text-muted-foreground">{`reasoning steps: ${reasoningStepCount}`}</span>
                      ) : null}
                      {task.error ? <span className="text-destructive">{task.error}</span> : null}
                    </div>
                  </summary>

                  {childRows.length > 0 ? (
                    <div className="mt-3 space-y-2 border-t pt-3">
                      {childRows.map((child) => {
                        const reportLink = runReportLink(child);
                        const childMeta = (child.meta ?? {}) as Record<string, unknown>;
                        const childStage = stageLabel(String(childMeta.last_stage ?? ""));
                        const childElapsed = elapsedLabel(childMeta.last_elapsed_ms);
                        const childStatusText = String(childMeta.status_text ?? "").trim();
                        return (
                          <div key={child.task_id} className="rounded-lg border bg-muted/10 p-2">
                            <div className="flex items-center justify-between gap-2">
                              <p className="truncate text-xs font-medium">{child.meta?.scenario ? String(child.meta.scenario) : child.task_type}</p>
                              <Badge variant={statusVariant(child.status)}>{child.status}</Badge>
                            </div>
                            <div className="mt-1 h-1.5 w-full rounded bg-muted/40">
                              <div className="h-1.5 rounded bg-primary transition-all" style={{ width: `${progressValue(child.progress)}%` }} />
                            </div>
                            <div className="mt-1 flex flex-wrap gap-3 text-[11px] text-muted-foreground">
                              <span>{progressValue(child.progress)}%</span>
                              <span>{`stage: ${childStage}${childElapsed ? ` (${childElapsed})` : ""}${childStatusText ? ` · ${childStatusText}` : ""}`}</span>
                              {reportLink ? (
                                <Link href={reportLink} className="text-primary underline">
                                  Open Report
                                </Link>
                              ) : null}
                              {child.error ? <span className="text-destructive">{child.error}</span> : null}
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  ) : null}
                </details>
              );
            })}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
