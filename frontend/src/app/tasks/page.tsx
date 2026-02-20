"use client";

import { EmptyState } from "@/components/common/empty-state";
import { useWorkbench } from "@/components/providers/workbench-provider";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";

export default function TasksPage() {
  const { loadingCore, tasks } = useWorkbench();

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
      ) : tasks.length === 0 ? (
        <EmptyState title="No tasks yet" description="Generate data or run a backtest to populate this list." />
      ) : (
        <div className="space-y-2">
          {tasks.map((task) => (
            <div key={task.task_id} className="rounded-xl border border-border p-3">
              <div className="flex items-center justify-between">
                <p className="text-sm font-medium">{task.task_type}</p>
                <Badge variant={task.status === "done" ? "success" : task.status === "failed" ? "destructive" : "warning"}>
                  {task.status}
                </Badge>
              </div>
              <p className="mt-1 text-xs text-muted-foreground">progress: {task.progress}%</p>
              {task.error ? <p className="mt-1 text-xs text-destructive">{task.error}</p> : null}
            </div>
          ))}
        </div>
      )}
      </CardContent>
    </Card>
  );
}
