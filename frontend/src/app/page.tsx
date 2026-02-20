"use client";

import Link from "next/link";
import { useState } from "react";
import { useRouter } from "next/navigation";
import { ArrowRight, Database, PlayCircle } from "lucide-react";

import { EmptyState } from "@/components/common/empty-state";
import { useWorkbench } from "@/components/providers/workbench-provider";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";

export default function DashboardPage() {
  const { loadingCore, runs, risk, generateDataset, runBacktest, latestDatasetVersion, restoreTraceContext } = useWorkbench();
  const router = useRouter();
  const [creatingDataset, setCreatingDataset] = useState(false);
  const [runningBacktest, setRunningBacktest] = useState(false);
  const [restoringRunId, setRestoringRunId] = useState<string | null>(null);
  const latestRun = runs[0];

  async function onGenerateDataset() {
    setCreatingDataset(true);
    try {
      await generateDataset();
    } finally {
      setCreatingDataset(false);
    }
  }

  async function onRunBacktest() {
    setRunningBacktest(true);
    try {
      await runBacktest();
    } finally {
      setRunningBacktest(false);
    }
  }

  async function onRestore(traceId: string, runId: string) {
    setRestoringRunId(runId);
    try {
      const bundle = await restoreTraceContext(traceId);
      const sessionId = bundle.session_state.session_id;
      router.push(`/chat?session_id=${encodeURIComponent(sessionId)}&restored_trace_id=${encodeURIComponent(traceId)}`);
    } finally {
      setRestoringRunId(null);
    }
  }

  return (
    <div className="grid gap-4 xl:grid-cols-12">
      <Card className="xl:col-span-8">
        <CardHeader>
          <CardTitle>Recent Runs</CardTitle>
          <CardDescription>Latest five backtest runs with risk profile snapshot.</CardDescription>
        </CardHeader>
        <CardContent>
          {loadingCore ? (
            <div className="space-y-2">
              {Array.from({ length: 5 }).map((_, i) => (
                <Skeleton key={i} className="h-14 w-full" />
              ))}
            </div>
          ) : runs.length === 0 ? (
            <EmptyState title="No runs yet" description="Generate a dataset and run a backtest to create your first report." />
          ) : (
            <div className="space-y-2">
              {runs.slice(0, 5).map((run) => (
                <div key={run.run_id} className="flex items-center justify-between rounded-lg border p-3 transition-colors hover:bg-accent/60">
                  <Link href={`/reports/${run.run_id}`} className="min-w-0 flex-1">
                    <p className="truncate text-sm font-semibold">{run.run_id}</p>
                    <p className="text-xs text-muted-foreground">
                      {run.market} | {run.start} to {run.end}
                    </p>
                  </Link>
                  <div className="ml-4 flex items-center gap-2 text-xs">
                    <Badge variant="muted">Sharpe {run.sharpe ?? "-"}</Badge>
                    <Badge variant={run.max_drawdown !== null && run.max_drawdown <= 0.1 ? "success" : "warning"}>
                      MDD {run.max_drawdown ?? "-"}
                    </Badge>
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={!run.audit_trace_id || restoringRunId === run.run_id}
                      onClick={() => run.audit_trace_id && onRestore(run.audit_trace_id, run.run_id)}
                    >
                      {restoringRunId === run.run_id ? "Restoring..." : "Restore"}
                    </Button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      <Card className="xl:col-span-4">
        <CardHeader>
          <CardTitle>Risk Gate</CardTitle>
          <CardDescription>Live trading remains locked by default.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-2 text-sm">
          <p>Mode: <span className="font-medium">{risk?.mode ?? "-"}</span></p>
          <p>Live trading: <span className="font-medium">{risk?.live_trading_enabled ? "enabled" : "disabled"}</span></p>
          <p>Kill switch: <span className="font-medium">{risk?.kill_switch_enabled ? "ON" : "OFF"}</span></p>
          <p className="text-xs text-muted-foreground">Approval workflow required before any live unlock.</p>
        </CardContent>
      </Card>

      <Card className="xl:col-span-12">
        <CardHeader>
          <CardTitle>Quick Actions</CardTitle>
          <CardDescription>Guide flow: dataset to backtest to report.</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-wrap items-center gap-2">
          <Button onClick={onGenerateDataset} disabled={creatingDataset}>
            <Database className="mr-1 h-4 w-4" />
            {creatingDataset ? "Generating..." : "Generate Dataset"}
          </Button>
          <Button variant="secondary" onClick={onRunBacktest} disabled={runningBacktest}>
            <PlayCircle className="mr-1 h-4 w-4" />
            {runningBacktest ? "Running..." : "Run Backtest"}
          </Button>
          <Button asChild variant="outline">
            <Link href={latestRun ? `/reports/${latestRun.run_id}` : "/reports"}>
              Open Latest Report
              <ArrowRight className="ml-1 h-4 w-4" />
            </Link>
          </Button>
          <Badge variant="muted">dataset: {latestDatasetVersion ?? "-"}</Badge>
        </CardContent>
      </Card>
    </div>
  );
}
