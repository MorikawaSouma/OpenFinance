"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { CheckCircle2, Circle, Download, Play } from "lucide-react";

import { EmptyState } from "@/components/common/empty-state";
import { useWorkbench } from "@/components/providers/workbench-provider";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { api } from "@/lib/api";

const stepOrder = [
  "plan.compose",
  "evidence.pack",
  "factor.define",
  "strategy.compose",
  "dataset.prepare",
  "backtest.run",
  "paper.trade",
  "risk.explain",
];

export default function PipelinePage() {
  const { mode, latestPipeline, runPipeline, pushToast } = useWorkbench();
  const [question, setQuestion] = useState(
    "Why is Nikkei volatility rising recently? Build a low-drawdown, high-Sharpe strategy."
  );
  const [market, setMarket] = useState("JP");
  const [highTurnoverMode, setHighTurnoverMode] = useState(false);
  const [autoAdjustForRules, setAutoAdjustForRules] = useState(false);
  const [confirmMigrationRisk, setConfirmMigrationRisk] = useState(false);
  const [running, setRunning] = useState(false);
  const [preflightWarnings, setPreflightWarnings] = useState<
    Array<{
      market: string;
      severity: string;
      title: string;
      explanation: string;
      suggestion?: string;
      code: string;
      variant_id?: string | null;
    }>
  >([]);

  const frameworkSections = useMemo(() => {
    const plan = latestPipeline?.research_plan;
    if (!plan) return [];
    return [
      { key: "value", label: "Value", payload: plan.value },
      { key: "macro", label: "Macro", payload: plan.macro },
      { key: "stats", label: "Stats", payload: plan.stats },
      { key: "behavior", label: "Behavior", payload: plan.behavior },
    ];
  }, [latestPipeline]);

  async function onRun() {
    setRunning(true);
    try {
      const constraints: Record<string, unknown> = {};
      if (highTurnoverMode) {
        constraints.factor_cost_sensitivity_level = "high";
        constraints.factor_expected_horizon = "intraday";
        constraints.expected_turnover = 0.65;
        constraints.expected_turnover_threshold = 0.35;
        constraints.auto_round_lot = false;
      }

      const planPreview = await api.createPlan({ question, market, constraints });
      const warnings = planPreview.preflight_warnings ?? [];
      setPreflightWarnings(warnings);
      const hasBlock = warnings.some((row) => row.severity === "block");
      if (hasBlock && !autoAdjustForRules && !confirmMigrationRisk) {
        pushToast("Preflight blocked", "Confirm migration risk or enable auto-adjust before running.", "error");
        return;
      }

      const result = await runPipeline(question, market, {
        planId: planPreview.plan_id,
        constraints,
        migrationPreflightConfirmed: confirmMigrationRisk,
        autoAdjustForMarketRules: autoAdjustForRules,
      });
      setPreflightWarnings(result.preflight_warnings ?? warnings);
      pushToast("Pipeline completed", `Run generated: ${result.run_id}`, "success");
    } catch (err) {
      pushToast("Pipeline failed", err instanceof Error ? err.message : "Unknown error", "error");
    } finally {
      setRunning(false);
    }
  }

  async function exportAuditBundle() {
    if (!latestPipeline) return;
    try {
      const logs = await api.getAudit(mode === "developer" ? latestPipeline.trace_id : undefined);
      const blob = new Blob([JSON.stringify({ pipeline: latestPipeline, logs }, null, 2)], {
        type: "application/json",
      });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `audit_bundle_${latestPipeline.run_id}.json`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      pushToast("Export failed", err instanceof Error ? err.message : "Unknown error", "error");
    }
  }

  return (
    <div className="grid gap-4">
      <Card>
        <CardHeader className="md:flex-row md:items-center md:justify-between">
          <div>
            <CardTitle>Pipeline Timeline</CardTitle>
            <CardDescription>Plan to evidence to factors to strategy to multi-run backtest.</CardDescription>
          </div>
          <div className="flex gap-2">
            <Button variant="outline" onClick={exportAuditBundle} disabled={!latestPipeline}>
              <Download className="mr-1 h-4 w-4" />
              Export Audit Bundle
            </Button>
            <Button onClick={onRun} disabled={running}>
              <Play className="mr-1 h-4 w-4" />
              {running ? "Running..." : "Run End-to-End"}
            </Button>
          </div>
        </CardHeader>
        <CardContent className="space-y-2">
          <div className="flex flex-wrap items-center gap-2">
            <Input
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              placeholder="Enter a research question. The system generates a plan and runs migration preflight."
              className="min-w-[260px] flex-1"
            />
            <select
              value={market}
              onChange={(e) => setMarket(e.target.value)}
              className="h-10 rounded-md border bg-background px-2 text-sm"
            >
              {["US", "CN", "JP", "CRYPTO"].map((item) => (
                <option key={item} value={item}>
                  {item}
                </option>
              ))}
            </select>
            <Badge variant={mode === "developer" ? "warning" : "success"}>
              {mode === "developer" ? "Developer Mode" : "User Mode"}
            </Badge>
          </div>
          <div className="flex flex-wrap items-center gap-3 text-xs text-muted-foreground">
            <label className="flex items-center gap-1">
              <input type="checkbox" checked={highTurnoverMode} onChange={(e) => setHighTurnoverMode(e.target.checked)} />
              High-frequency / intraday profile
            </label>
            <label className="flex items-center gap-1">
              <input type="checkbox" checked={autoAdjustForRules} onChange={(e) => setAutoAdjustForRules(e.target.checked)} />
              Auto-adjust to market rules
            </label>
            <label className="flex items-center gap-1">
              <input type="checkbox" checked={confirmMigrationRisk} onChange={(e) => setConfirmMigrationRisk(e.target.checked)} />
              Confirm migration risk and continue
            </label>
          </div>
        </CardContent>
      </Card>

      {preflightWarnings.length > 0 ? (
        <Card>
          <CardHeader>
            <CardTitle>Migration Preflight</CardTitle>
            <CardDescription>
              Pre-run market structure warnings for T+1, lot size, and trading session differences.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-2 text-xs">
            {preflightWarnings.map((row, idx) => (
              <div key={`${row.code}-${row.variant_id ?? "global"}-${idx}`} className="rounded-md border p-2">
                <div className="flex items-center gap-2">
                  <Badge variant={row.severity === "block" ? "destructive" : "warning"}>{row.severity}</Badge>
                  <p className="font-semibold">
                    [{row.market}] {row.title}
                  </p>
                </div>
                <p className="mt-1 text-muted-foreground">{row.explanation}</p>
                {row.suggestion ? <p className="mt-1 text-foreground">Suggestion: {row.suggestion}</p> : null}
              </div>
            ))}
          </CardContent>
        </Card>
      ) : null}

      {running ? (
        <Card>
          <CardHeader>
            <CardTitle>Executing...</CardTitle>
            <CardDescription>Preparing full timeline and report assets.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-2">
            {stepOrder.map((step) => (
              <Skeleton key={step} className="h-12 w-full" />
            ))}
          </CardContent>
        </Card>
      ) : null}

      {!latestPipeline ? (
        <EmptyState title="No pipeline run yet" description="Run once to generate plan and experiment comparison." />
      ) : (
        <>
          <Card>
            <CardHeader className="md:flex-row md:items-center md:justify-between">
              <div>
                <CardTitle>Stepper</CardTitle>
                <CardDescription>Each step card expands input/output summary.</CardDescription>
              </div>
              <Button asChild variant="secondary">
                <Link href={`/reports/${latestPipeline.run_id}`}>Open Run Report</Link>
              </Button>
            </CardHeader>
            <CardContent>
              <ol className="space-y-3">
                {latestPipeline.steps.map((step, idx) => {
                  const done = step.status === "done";
                  return (
                    <li key={`${step.name}-${idx}`} className="rounded-lg border p-3">
                      <div className="flex items-center justify-between gap-2">
                        <div className="flex items-center gap-2">
                          {done ? <CheckCircle2 className="h-4 w-4 text-success" /> : <Circle className="h-4 w-4 text-muted-foreground" />}
                          <p className="text-sm font-semibold">{step.name}</p>
                        </div>
                        <Badge variant={done ? "success" : "warning"}>{step.status}</Badge>
                      </div>
                    </li>
                  );
                })}
              </ol>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Plan Snapshot</CardTitle>
              <CardDescription>Question-specific objectives and four-lens framework.</CardDescription>
            </CardHeader>
            <CardContent className="grid gap-2 text-xs text-muted-foreground">
              <p>plan_id: {latestPipeline.plan_id}</p>
              <p>objectives: {latestPipeline.research_plan.objectives.join(", ")}</p>
              <p>families: {latestPipeline.research_plan.candidate_strategy_families.join(", ")}</p>
              {frameworkSections.length > 0 ? (
                <Tabs defaultValue="value">
                  <TabsList>
                    {frameworkSections.map((section) => (
                      <TabsTrigger key={`framework-tab-${section.key}`} value={section.key}>
                        {section.label}
                      </TabsTrigger>
                    ))}
                  </TabsList>
                  {frameworkSections.map((section) => (
                    <TabsContent key={`framework-content-${section.key}`} value={section.key}>
                      <p>{(section.payload?.hypotheses ?? []).join(" | ") || "-"}</p>
                    </TabsContent>
                  ))}
                </Tabs>
              ) : null}
            </CardContent>
          </Card>
        </>
      )}
    </div>
  );
}
