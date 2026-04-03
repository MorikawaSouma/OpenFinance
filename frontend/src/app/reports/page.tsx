"use client";

import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";

import { EmptyState } from "@/components/common/empty-state";
import { useCatalogSummaryActions, useCatalogSummaryState } from "@/components/providers/catalog-summary-provider";
import { useResearchContextState, useResearchRestoreActions } from "@/components/providers/research-context-provider";
import { useTaskRealtimeState } from "@/components/providers/task-realtime-provider";
import { useWorkbenchShellActions } from "@/components/providers/workbench-shell-provider";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TBody, Td, Th, THead, Tr } from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { api } from "@/lib/api";
import { messages } from "@/lib/messages";
import type {
  BacktestEvaluationPlan,
  BacktestReport,
  MultiMarketCompareResponse,
  PipelineResponse,
  RobustnessReport,
  StrategyCompilationPlan,
  StrategySpec,
  StrategyValidationResult,
  TaskRecord,
} from "@/lib/types";

function toNum(value: unknown): number | null {
  return typeof value === "number" ? value : null;
}

function extractPipelineResponse(task: TaskRecord): PipelineResponse | null {
  if (String(task.task_type) !== "pipeline_run") return null;
  const result = task.result && typeof task.result === "object" ? (task.result as Record<string, unknown>) : {};
  const payload = result.pipeline_response;
  return payload && typeof payload === "object" ? (payload as PipelineResponse) : null;
}

function validationBadgeVariant(status: string) {
  if (status === "invalid") return "destructive" as const;
  if (status === "warn") return "warning" as const;
  return "success" as const;
}

function parseEvaluationPlan(value: unknown): BacktestEvaluationPlan | null {
  if (!value || typeof value !== "object") return null;
  const payload = value as Record<string, unknown>;
  if (typeof payload.schema_version !== "string") return null;
  return payload as BacktestEvaluationPlan;
}

const MARKET_OPTIONS = ["US", "CN", "JP", "CRYPTO"] as const;
const STRATEGY_FAMILIES = ["trend", "mean_reversion", "value", "risk_parity"] as const;
const REBALANCE_OPTIONS = ["daily", "weekly", "biweekly", "monthly"] as const;

export default function ReportsPage() {
  const { refreshRuns } = useCatalogSummaryActions();
  const { runs, isRunsBootstrapPending } = useCatalogSummaryState();
  const { lastSessionId } = useResearchContextState();
  const { restoreTraceToResearchContext } = useResearchRestoreActions();
  const { tasks } = useTaskRealtimeState();
  const { pushToast } = useWorkbenchShellActions();
  const router = useRouter();

  const [runA, setRunA] = useState("");
  const [runB, setRunB] = useState("");
  const [compareLoading, setCompareLoading] = useState(false);
  const [reportA, setReportA] = useState<BacktestReport | null>(null);
  const [reportB, setReportB] = useState<BacktestReport | null>(null);
  const [restoringRunId, setRestoringRunId] = useState<string | null>(null);

  const [multiMarketLoading, setMultiMarketLoading] = useState(false);
  const [multiMarketResult, setMultiMarketResult] = useState<MultiMarketCompareResponse | null>(null);
  const [multiMarketTaskId, setMultiMarketTaskId] = useState("");
  const [multiMarkets, setMultiMarkets] = useState<string[]>(["US", "JP"]);
  const [multiStrategyFamily, setMultiStrategyFamily] = useState("trend");
  const [multiRebalance, setMultiRebalance] = useState("weekly");
  const [multiLookback, setMultiLookback] = useState(20);
  const [multiStart, setMultiStart] = useState("2024-01-01");
  const [multiEnd, setMultiEnd] = useState("2024-03-31");
  const [multiCommission, setMultiCommission] = useState(5);
  const [multiSlippage, setMultiSlippage] = useState(8);

  const [robustnessLoading, setRobustnessLoading] = useState(false);
  const [robustnessResult, setRobustnessResult] = useState<RobustnessReport | null>(null);
  const [robustnessTaskId, setRobustnessTaskId] = useState("");
  const [robustStrategyFamily, setRobustStrategyFamily] = useState("trend");
  const [robustRebalance, setRobustRebalance] = useState("weekly");
  const [robustLookback, setRobustLookback] = useState(20);
  const [robustThreshold, setRobustThreshold] = useState(0);
  const [robustStart, setRobustStart] = useState("2024-01-01");
  const [robustEnd, setRobustEnd] = useState("2024-03-31");
  const [robustCommission, setRobustCommission] = useState(5);
  const [robustSlippage, setRobustSlippage] = useState(8);
  const [robustMaxVariants, setRobustMaxVariants] = useState(8);
  const multiMarketTaskEventRef = useRef("");
  const robustnessTaskEventRef = useRef("");
  const sessionTaskScope = useMemo(() => (lastSessionId || "reports").trim(), [lastSessionId]);

  useEffect(() => {
    void refreshRuns().catch(() => undefined);
  }, [refreshRuns]);

  const latestPipeline = useMemo(() => {
    for (const task of tasks) {
      const payload = extractPipelineResponse(task);
      if (payload) return payload;
    }
    return null;
  }, [tasks]);

  const metricsRows = useMemo(() => {
    if (!reportA || !reportB) return [];
    const keys = Array.from(new Set([...Object.keys(reportA.metrics), ...Object.keys(reportB.metrics)]));
    return keys.map((key) => {
      const a = reportA.metrics[key];
      const b = reportB.metrics[key];
      const aNum = toNum(a);
      const bNum = toNum(b);
      return {
        key,
        a: String(a ?? "-"),
        b: String(b ?? "-"),
        diff: aNum !== null && bNum !== null ? (aNum - bNum).toFixed(6) : "-",
      };
    });
  }, [reportA, reportB]);

  const multiMarketTask = useMemo(
    () =>
      tasks.find((row) => String(row.task_id) === multiMarketTaskId) ??
      tasks.find((row) => {
        if (String(row.task_type) !== "multi_market.compare") return false;
        const metaSession = String((row.meta ?? {}).session_id ?? "").trim();
        return metaSession === sessionTaskScope;
      }) ??
      null,
    [multiMarketTaskId, sessionTaskScope, tasks]
  );
  const robustnessTask = useMemo(
    () =>
      tasks.find((row) => String(row.task_id) === robustnessTaskId) ??
      tasks.find((row) => {
        if (String(row.task_type) !== "robustness.run") return false;
        const metaSession = String((row.meta ?? {}).session_id ?? "").trim();
        return metaSession === sessionTaskScope;
      }) ??
      null,
    [robustnessTaskId, sessionTaskScope, tasks]
  );
  const multiMarketTaskRunning = useMemo(() => {
    if (!multiMarketTask) return false;
    const status = String(multiMarketTask.status || "").toLowerCase();
    return !["done", "error", "failed", "canceled"].includes(status);
  }, [multiMarketTask]);
  const robustnessTaskRunning = useMemo(() => {
    if (!robustnessTask) return false;
    const status = String(robustnessTask.status || "").toLowerCase();
    return !["done", "error", "failed", "canceled"].includes(status);
  }, [robustnessTask]);

  useEffect(() => {
    if (!multiMarketTask) return;
    const status = String(multiMarketTask.status || "").toLowerCase();
    const eventKey = `${multiMarketTask.task_id}:${status}`;
    if (multiMarketTaskEventRef.current === eventKey) return;
    multiMarketTaskEventRef.current = eventKey;
    const result = multiMarketTask.result && typeof multiMarketTask.result === "object" ? (multiMarketTask.result as Record<string, unknown>) : {};
    if (status === "done") {
      const rowsRaw = Array.isArray(result.rows) ? result.rows : [];
      const typedDiffRows = Array.isArray((result.result_details as { diff_rows?: unknown } | undefined)?.diff_rows)
        ? ((result.result_details as { diff_rows?: unknown }).diff_rows as MultiMarketCompareResponse["diff_table"])
        : null;
      const diffRaw = Array.isArray(result.diff_table) ? result.diff_table : [];
      setMultiMarketResult({
        compare_id: String(result.compare_id ?? ""),
        baseline_market: String(result.baseline_market ?? ""),
        strategy_spec: (result.strategy_spec && typeof result.strategy_spec === "object" ? result.strategy_spec : {}) as StrategySpec,
        strategy_validation: (
          result.strategy_validation && typeof result.strategy_validation === "object" ? result.strategy_validation : {}
        ) as StrategyValidationResult,
        strategy_compilation: (
          result.strategy_compilation && typeof result.strategy_compilation === "object" ? result.strategy_compilation : {}
        ) as StrategyCompilationPlan,
        outcome_summary: (
          result.outcome_summary && typeof result.outcome_summary === "object" ? result.outcome_summary : null
        ) as MultiMarketCompareResponse["outcome_summary"],
        result_details: (
          result.result_details && typeof result.result_details === "object" ? result.result_details : null
        ) as MultiMarketCompareResponse["result_details"],
        rows: rowsRaw as MultiMarketCompareResponse["rows"],
        diff_table: ((typedDiffRows as MultiMarketCompareResponse["diff_table"] | null) ?? diffRaw) as MultiMarketCompareResponse["diff_table"],
        parent_task_id: String(multiMarketTask.task_id),
        child_task_ids: [],
        migration_warnings: [],
        market_warnings: {},
      });
      return;
    }
    if (status === "error" || status === "failed" || status === "canceled") {
      pushToast("Multi-market comparison failed", String(multiMarketTask.error || multiMarketTask.message || "Task failed"), "error");
    }
  }, [multiMarketTask, pushToast]);

  useEffect(() => {
    if (!robustnessTask) return;
    const status = String(robustnessTask.status || "").toLowerCase();
    const eventKey = `${robustnessTask.task_id}:${status}`;
    if (robustnessTaskEventRef.current === eventKey) return;
    robustnessTaskEventRef.current = eventKey;
    const result = robustnessTask.result && typeof robustnessTask.result === "object" ? (robustnessTask.result as Record<string, unknown>) : {};
    if (status === "done") {
      const report = result.report;
      if (report && typeof report === "object") {
        setRobustnessResult(report as RobustnessReport);
      }
      return;
    }
    if (status === "error" || status === "failed" || status === "canceled") {
      pushToast("Robustness analysis failed", String(robustnessTask.error || robustnessTask.message || "Task failed"), "error");
    }
  }, [pushToast, robustnessTask]);

  async function compareRuns() {
    if (!runA || !runB) {
      pushToast("Select two runs", "Select Run A and Run B first.", "error");
      return;
    }
    setCompareLoading(true);
    try {
      const [a, b] = await Promise.all([api.getRun(runA), api.getRun(runB)]);
      setReportA(a);
      setReportB(b);
      pushToast("Comparison complete", "Metrics diff table updated.", "success");
    } catch (err) {
      setReportA(null);
      setReportB(null);
      pushToast("Comparison failed", err instanceof Error ? err.message : "Unknown error", "error");
    } finally {
      setCompareLoading(false);
    }
  }

  async function onRestore(traceId: string, runId: string) {
    setRestoringRunId(runId);
    try {
      const bundle = await restoreTraceToResearchContext(traceId);
      const sessionId = bundle.session_state.session_id;
      router.push(`/chat?session_id=${encodeURIComponent(sessionId)}&restored_trace_id=${encodeURIComponent(traceId)}`);
    } finally {
      setRestoringRunId(null);
    }
  }

  function toggleMarket(market: string) {
    setMultiMarkets((prev) => (prev.includes(market) ? prev.filter((item) => item !== market) : [...prev, market]));
  }

  async function runMultiMarketCompare() {
    if (multiMarkets.length < 2) {
      pushToast("Select markets", "Select at least two markets for comparison.", "error");
      return;
    }
    setMultiMarketLoading(true);
    try {
      const task = await api.submitMultiMarketCompare({
        markets: multiMarkets,
        strategy_id: "multi_market_strategy",
        strategy_version: `mm-${multiStrategyFamily}-${multiRebalance}`,
        strategy_family: multiStrategyFamily,
        rebalance: multiRebalance,
        lookback_days: multiLookback,
        signal_threshold: 0,
        position_sizing: "risk_budget",
        risk_budget: "vol_target_10pct",
        max_position: 0.12,
        leverage_limit: 1.0,
        auto_round_lot: true,
        start: multiStart,
        end: multiEnd,
        seed: 42,
        commission_bps: multiCommission,
        slippage_bps: multiSlippage,
        session_id: sessionTaskScope,
      });
      setMultiMarketTaskId(String(task.task_id));
      setMultiMarketResult(null);
      pushToast("Task submitted", `Multi-market compare task ${String(task.task_id).slice(0, 8)} is running.`, "success");
    } catch (err) {
      setMultiMarketResult(null);
      pushToast("Multi-market comparison failed", err instanceof Error ? err.message : "Unknown error", "error");
    } finally {
      setMultiMarketLoading(false);
    }
  }

  async function runRobustnessSuite() {
    const latestDatasetVersion = runs[0]?.dataset_version;
    if (!latestDatasetVersion) {
      pushToast("No dataset version", "Generate a dataset or run a backtest first.", "error");
      return;
    }
    setRobustnessLoading(true);
    try {
      const task = await api.submitRobustness({
        dataset_version: latestDatasetVersion,
        strategy_id: "robustness_suite",
        strategy_version: `robust-${robustStrategyFamily}-${robustRebalance}`,
        market: "US",
        start: robustStart,
        end: robustEnd,
        strategy_family: robustStrategyFamily,
        rebalance: robustRebalance,
        lookback_days: robustLookback,
        signal_threshold: robustThreshold,
        position_sizing: "risk_budget",
        risk_budget: "vol_target_10pct",
        max_position: 0.12,
        leverage_limit: 1.0,
        auto_round_lot: true,
        commission_bps: robustCommission,
        slippage_bps: robustSlippage,
        cost_multipliers: [0.5, 1.0, 2.0],
        max_variants: robustMaxVariants,
        session_id: sessionTaskScope,
      });
      setRobustnessTaskId(String(task.task_id));
      setRobustnessResult(null);
      pushToast("Task submitted", `Robustness task ${String(task.task_id).slice(0, 8)} is running.`, "success");
    } catch (err) {
      setRobustnessResult(null);
      pushToast("Robustness analysis failed", err instanceof Error ? err.message : "Unknown error", "error");
    } finally {
      setRobustnessLoading(false);
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>{messages.reports.title}</CardTitle>
        <CardDescription>{messages.reports.desc}</CardDescription>
      </CardHeader>
      <CardContent>
        {latestPipeline && latestPipeline.comparison_table.length > 0 ? (
          <div className="mb-4 rounded-lg border p-3">
            <p className="text-sm font-semibold">{messages.reports.experimentMatrix}</p>
            <p className="mb-2 text-xs text-muted-foreground">
              Plan ID: {latestPipeline.plan_id} | Compared {latestPipeline.comparison_table.length} variants
            </p>
          </div>
        ) : null}

        <Tabs defaultValue="list">
          <TabsList>
            <TabsTrigger value="list">{messages.reports.runList}</TabsTrigger>
            <TabsTrigger value="compare">{messages.reports.compare}</TabsTrigger>
            <TabsTrigger value="multi-market">{messages.reports.multiMarket}</TabsTrigger>
            <TabsTrigger value="robustness">{messages.reports.robustness}</TabsTrigger>
          </TabsList>

          <TabsContent value="list">
            {isRunsBootstrapPending ? (
              <div className="space-y-2">
                {Array.from({ length: 6 }).map((_, i) => (
                  <Skeleton key={i} className="h-12 w-full" />
                ))}
              </div>
            ) : runs.length === 0 ? (
              <EmptyState title={messages.reports.noReportsTitle} description={messages.reports.noReportsDesc} />
            ) : (
              <div className="space-y-2">
                {runs.map((run) => (
                  <div key={run.run_id} className="rounded-lg border p-3 transition-colors hover:bg-accent/60">
                    <div className="flex items-center justify-between gap-2">
                      <Link href={`/reports/${run.run_id}`} className="text-sm font-semibold">
                        {run.run_id}
                      </Link>
                      <div className="flex gap-1">
                        <Badge variant="muted">Sharpe {run.sharpe ?? "-"}</Badge>
                        <Badge variant="muted">MDD {run.max_drawdown ?? "-"}</Badge>
                        <Button
                          size="sm"
                          variant="outline"
                          disabled={!run.audit_trace_id || restoringRunId === run.run_id}
                          onClick={() => run.audit_trace_id && onRestore(run.audit_trace_id, run.run_id)}
                        >
                          {restoringRunId === run.run_id ? messages.reports.restoring : messages.reports.restore}
                        </Button>
                      </div>
                    </div>
                    <p className="mt-1 text-xs text-muted-foreground">
                      {run.market} | {run.start} to {run.end}
                    </p>
                  </div>
                ))}
              </div>
            )}
          </TabsContent>

          <TabsContent value="compare" className="space-y-3">
            <div className="grid gap-2 md:grid-cols-4">
              <select value={runA} onChange={(e) => setRunA(e.target.value)} className="h-9 rounded-md border border-input bg-background px-3 text-sm">
                <option value="">{messages.reports.selectRunA}</option>
                {runs.map((run) => (
                  <option key={`a-${run.run_id}`} value={run.run_id}>
                    {run.run_id}
                  </option>
                ))}
              </select>
              <select value={runB} onChange={(e) => setRunB(e.target.value)} className="h-9 rounded-md border border-input bg-background px-3 text-sm">
                <option value="">{messages.reports.selectRunB}</option>
                {runs.map((run) => (
                  <option key={`b-${run.run_id}`} value={run.run_id}>
                    {run.run_id}
                  </option>
                ))}
              </select>
              <Button onClick={compareRuns} disabled={compareLoading} className="md:col-span-2">
                {compareLoading ? messages.reports.comparing : messages.reports.compareAction}
              </Button>
            </div>
            {metricsRows.length === 0 ? (
              <EmptyState title={messages.reports.noComparisonTitle} description={messages.reports.noComparisonDesc} />
            ) : (
              <Table>
                <THead>
                  <tr>
                    <Th>{messages.reports.metric}</Th>
                    <Th>{messages.reports.runA}</Th>
                    <Th>{messages.reports.runB}</Th>
                    <Th>{messages.reports.diff}</Th>
                  </tr>
                </THead>
                <TBody>
                  {metricsRows.map((row) => (
                    <Tr key={row.key}>
                      <Td>{row.key}</Td>
                      <Td>{row.a}</Td>
                      <Td>{row.b}</Td>
                      <Td>{row.diff}</Td>
                    </Tr>
                  ))}
                </TBody>
              </Table>
            )}
          </TabsContent>

          <TabsContent value="multi-market" className="space-y-3">
            <div className="flex flex-wrap gap-2">
              {MARKET_OPTIONS.map((market) => (
                <Button key={market} variant={multiMarkets.includes(market) ? "default" : "outline"} size="sm" onClick={() => toggleMarket(market)}>
                  {market}
                </Button>
              ))}
            </div>
            <div className="grid gap-2 md:grid-cols-3">
              <select value={multiStrategyFamily} onChange={(e) => setMultiStrategyFamily(e.target.value)} className="h-9 rounded-md border border-input bg-background px-3 text-sm">
                {STRATEGY_FAMILIES.map((item) => (
                  <option key={item} value={item}>
                    {item}
                  </option>
                ))}
              </select>
              <select value={multiRebalance} onChange={(e) => setMultiRebalance(e.target.value)} className="h-9 rounded-md border border-input bg-background px-3 text-sm">
                {REBALANCE_OPTIONS.map((item) => (
                  <option key={item} value={item}>
                    {item}
                  </option>
                ))}
              </select>
              <input value={multiLookback} onChange={(e) => setMultiLookback(Number(e.target.value || 20))} type="number" min={2} max={252} className="h-9 rounded-md border border-input bg-background px-3 text-sm" placeholder="Lookback window" />
              <input value={multiStart} onChange={(e) => setMultiStart(e.target.value)} type="date" className="h-9 rounded-md border border-input bg-background px-3 text-sm" />
              <input value={multiEnd} onChange={(e) => setMultiEnd(e.target.value)} type="date" className="h-9 rounded-md border border-input bg-background px-3 text-sm" />
              <Button onClick={runMultiMarketCompare} disabled={multiMarketLoading || multiMarketTaskRunning}>
                {multiMarketLoading || multiMarketTaskRunning ? "Comparing..." : "Run multi-market comparison"}
              </Button>
              <input value={multiCommission} onChange={(e) => setMultiCommission(Number(e.target.value || 0))} type="number" min={0} className="h-9 rounded-md border border-input bg-background px-3 text-sm" placeholder="Commission bps" />
              <input value={multiSlippage} onChange={(e) => setMultiSlippage(Number(e.target.value || 0))} type="number" min={0} className="h-9 rounded-md border border-input bg-background px-3 text-sm" placeholder="Slippage bps" />
            </div>
            {multiMarketTask ? (
              <p className="text-xs text-muted-foreground">
                Task {String(multiMarketTask.task_id).slice(0, 8)} · {String(multiMarketTask.status)} · {Number(multiMarketTask.progress || 0)}%
              </p>
            ) : null}
            {!multiMarketResult ? (
              <EmptyState title="No multi-market comparison yet" description="Run comparison after selecting at least two markets." />
            ) : (
              <div className="space-y-3">
                {(() => {
                  const validation = multiMarketResult.strategy_validation;
                  const compilation = multiMarketResult.strategy_compilation;
                  return (
                <div className="rounded-lg border p-3 text-xs text-muted-foreground">
                  <p className="font-medium text-foreground">Base Strategy Spec</p>
                  <p className="mt-1">
                    {multiMarketResult.strategy_spec.strategy_family} / {multiMarketResult.strategy_spec.position_sizing} / {multiMarketResult.strategy_spec.rebalance}
                  </p>
                  <p className="mt-1">
                    market={multiMarketResult.strategy_spec.market} | risk_budget={multiMarketResult.strategy_spec.risk_budget} | simulation_only={multiMarketResult.strategy_spec.simulation_only ? "true" : "false"}
                  </p>
                  {multiMarketResult.outcome_summary ? (
                    <>
                      <p className="mt-2">outcome: {multiMarketResult.outcome_summary.summary}</p>
                      <p className="mt-1">
                        best_sharpe={multiMarketResult.outcome_summary.best_market_by_sharpe ?? "n/a"} | worst_mdd={multiMarketResult.outcome_summary.worst_market_by_drawdown ?? "n/a"} | warnings={multiMarketResult.outcome_summary.warning_count}
                      </p>
                      {multiMarketResult.rows.some((row) => row.action_regime_details) ? (
                        <p className="mt-1">
                          typed_actions: {multiMarketResult.rows.map((row) => {
                            const details = row.action_regime_details;
                            return `${row.market} ra=${details?.risk_actions.length ?? 0}/rp=${details?.regime_periods.length ?? 0}`;
                          }).join(" | ")}
                        </p>
                      ) : null}
                      {multiMarketResult.rows.some((row) => row.control_optimizer_details) ? (
                        <p className="mt-1">
                          typed_controls: {multiMarketResult.rows.map((row) => {
                            const details = row.control_optimizer_details;
                            return `${row.market} ro=${details?.rejected_orders.length ?? 0}/cb=${details?.circuit_breaker_intervals.length ?? 0}/risk=${details?.risk_contribution_points.length ?? 0}`;
                          }).join(" | ")}
                        </p>
                      ) : null}
                      {multiMarketResult.rows.some((row) => row.control_action_deep_details) ? (
                        <p className="mt-1">
                          typed_deep_controls: {multiMarketResult.rows.map((row) => {
                            const details = row.control_action_deep_details;
                            return `${row.market} steps=${details?.optimizer_steps.length ?? 0}/cb_rule=${details?.circuit_breaker_state.rule_type ?? "n/a"}/peak_l1=${details?.budget_breakdown.peak_deviation_l1 ?? "n/a"}`;
                          }).join(" | ")}
                        </p>
                      ) : null}
                      {multiMarketResult.rows.some((row) => row.attribution_execution_details) ? (
                        <p className="mt-1">
                          typed_attribution_exec: {multiMarketResult.rows.map((row) => {
                            const details = row.attribution_execution_details;
                            return `${row.market} cost=${details?.cost_detail.total_cost ?? "n/a"}/fill=${details?.execution_style_detail.fill_rate ?? "n/a"}/top_instr=${details?.attribution_detail.top_instrument?.label ?? "n/a"}`;
                          }).join(" | ")}
                        </p>
                      ) : null}
                    </>
                  ) : null}
                  {validation && typeof validation.summary === "string" ? (
                    <>
                      <div className="mt-2 flex flex-wrap items-center gap-2">
                        <Badge variant={validationBadgeVariant(validation.status)}>
                          {validation.status}
                        </Badge>
                        <Badge variant="muted">
                          next={validation.next_output}
                        </Badge>
                        {compilation && typeof compilation.summary === "string" ? (
                          <Badge variant="muted">
                            overlays={compilation.overlays.length}
                          </Badge>
                        ) : null}
                      </div>
                      <p className="mt-2">{validation.summary}</p>
                      {compilation && typeof compilation.summary === "string" ? (
                        <>
                          <p className="mt-2">compile: {compilation.summary}</p>
                          {compilation.compilation_profile?.summary ? (
                            <p className="mt-2">profile: {compilation.compilation_profile.summary}</p>
                          ) : null}
                          {compilation.compilation_policy?.summary ? (
                            <p className="mt-2">policy: {compilation.compilation_policy.summary}</p>
                          ) : null}
                        </>
                      ) : null}
                    </>
                  ) : (
                    <p className="mt-2">Validation unavailable for this comparison artifact.</p>
                  )}
                </div>
                  );
                })()}
                <Table>
                  <THead>
                    <tr>
                      <Th>Market</Th>
                      <Th>Sharpe</Th>
                      <Th>MDD</Th>
                      <Th>Turnover</Th>
                      <Th>Run</Th>
                    </tr>
                  </THead>
                  <TBody>
                    {(multiMarketResult.result_details?.diff_rows ?? multiMarketResult.diff_table).map((row, idx) => (
                      <Tr key={`${String(row.market)}-${idx}`}>
                        <Td>{String(row.market)}</Td>
                        <Td>{String(row.sharpe)}</Td>
                        <Td>{String(row.max_drawdown)}</Td>
                        <Td>{String(row.turnover)}</Td>
                        <Td><Link href={`/reports/${String(row.run_id)}`} className="text-primary underline">{String(row.run_id)}</Link></Td>
                      </Tr>
                    ))}
                  </TBody>
                </Table>
              </div>
            )}
          </TabsContent>

          <TabsContent value="robustness" className="space-y-3">
            <div className="grid gap-2 md:grid-cols-4">
              <select value={robustStrategyFamily} onChange={(e) => setRobustStrategyFamily(e.target.value)} className="h-9 rounded-md border border-input bg-background px-3 text-sm">
                {STRATEGY_FAMILIES.map((item) => (
                  <option key={`rb-sf-${item}`} value={item}>{item}</option>
                ))}
              </select>
              <select value={robustRebalance} onChange={(e) => setRobustRebalance(e.target.value)} className="h-9 rounded-md border border-input bg-background px-3 text-sm">
                {REBALANCE_OPTIONS.map((item) => (
                  <option key={`rb-rb-${item}`} value={item}>{item}</option>
                ))}
              </select>
              <input value={robustLookback} onChange={(e) => setRobustLookback(Number(e.target.value || 20))} type="number" min={2} max={252} className="h-9 rounded-md border border-input bg-background px-3 text-sm" placeholder="Lookback window" />
              <input value={robustThreshold} onChange={(e) => setRobustThreshold(Number(e.target.value || 0))} type="number" step={0.001} className="h-9 rounded-md border border-input bg-background px-3 text-sm" placeholder="Threshold" />
              <input value={robustStart} onChange={(e) => setRobustStart(e.target.value)} type="date" className="h-9 rounded-md border border-input bg-background px-3 text-sm" />
              <input value={robustEnd} onChange={(e) => setRobustEnd(e.target.value)} type="date" className="h-9 rounded-md border border-input bg-background px-3 text-sm" />
              <input value={robustCommission} onChange={(e) => setRobustCommission(Number(e.target.value || 0))} type="number" min={0} className="h-9 rounded-md border border-input bg-background px-3 text-sm" placeholder="Commission bps" />
              <input value={robustSlippage} onChange={(e) => setRobustSlippage(Number(e.target.value || 0))} type="number" min={0} className="h-9 rounded-md border border-input bg-background px-3 text-sm" placeholder="Slippage bps" />
              <input value={robustMaxVariants} onChange={(e) => setRobustMaxVariants(Number(e.target.value || 8))} type="number" min={6} max={24} className="h-9 rounded-md border border-input bg-background px-3 text-sm" placeholder="Max variants" />
              <Button onClick={runRobustnessSuite} disabled={robustnessLoading || robustnessTaskRunning} className="md:col-span-3">
                {robustnessLoading || robustnessTaskRunning ? "Running..." : "Run robustness suite"}
              </Button>
            </div>
            {robustnessTask ? (
              <p className="text-xs text-muted-foreground">
                Task {String(robustnessTask.task_id).slice(0, 8)} · {String(robustnessTask.status)} · {Number(robustnessTask.progress || 0)}%
              </p>
            ) : null}
            {!robustnessResult ? (
              <EmptyState title="No robustness report yet" description="Run robustness suite to generate variants." />
            ) : (
              <div className="space-y-3">
                {(() => {
                  const validation = robustnessResult.base_strategy_validation;
                  const compilation = robustnessResult.base_strategy_compilation;
                  return (
                <div className="rounded-lg border p-3 text-xs text-muted-foreground">
                  {(() => {
                    const evaluationPlan = parseEvaluationPlan(robustnessResult.base_backtest_request.evaluation_plan);
                    return (
                      <>
                  <p className="font-medium text-foreground">Base Strategy vs Runtime Request</p>
                  <p className="mt-1">
                    spec={robustnessResult.base_strategy_spec.strategy_family}/{robustnessResult.base_strategy_spec.position_sizing}/{robustnessResult.base_strategy_spec.rebalance}
                  </p>
                  <p className="mt-1">
                    execution_model={robustnessResult.base_backtest_request.execution_model} | eval_plan={evaluationPlan?.schema_version ?? "legacy"} | variants={robustnessResult.analysis_config.min_variants}-{robustnessResult.analysis_config.max_variants}
                  </p>
                  {evaluationPlan ? (
                    <p className="mt-1">
                      factor_lineage={evaluationPlan.factor_versions.length} | evidence_refs={evaluationPlan.evidence_refs.length} | request_profile={evaluationPlan.request_input_profile?.provenance_mode ?? "n/a"}
                    </p>
                  ) : null}
                  {robustnessResult.outcome_summary ? (
                    <>
                      <p className="mt-2">outcome: {robustnessResult.outcome_summary.summary}</p>
                      <p className="mt-1">
                        worst_case_run={robustnessResult.outcome_summary.worst_case_run_id ?? "n/a"} | worst_case_source={robustnessResult.outcome_summary.worst_case_source_type ?? "n/a"}
                      </p>
                      {robustnessResult.outcome_summary.base_runtime_summary ? (
                        <p className="mt-1">
                          base_runtime={robustnessResult.outcome_summary.base_runtime_summary.summary}
                        </p>
                      ) : null}
                      {robustnessResult.variants.some((row) => row.action_regime_details) ? (
                        <p className="mt-1">
                          typed_action_details={robustnessResult.variants.filter((row) => row.action_regime_details).length} variants | failure_variants={robustnessResult.variants.filter((row) => (row.action_regime_details?.failure_condition_events.length ?? 0) > 0).length}
                        </p>
                      ) : null}
                      {robustnessResult.variants.some((row) => row.control_optimizer_details) ? (
                        <p className="mt-1">
                          typed_control_details={robustnessResult.variants.filter((row) => row.control_optimizer_details).length} variants | reject_variants={robustnessResult.variants.filter((row) => (row.control_optimizer_details?.rejected_orders.length ?? 0) > 0).length}
                        </p>
                      ) : null}
                      {robustnessResult.variants.some((row) => row.control_action_deep_details) ? (
                        <p className="mt-1">
                          typed_deep_controls={robustnessResult.variants.filter((row) => row.control_action_deep_details).length} variants | cb_variants={robustnessResult.variants.filter((row) => (row.control_action_deep_details?.circuit_breaker_state.intervals.length ?? 0) > 0).length}
                        </p>
                      ) : null}
                      {robustnessResult.variants.some((row) => row.attribution_execution_details) ? (
                        <p className="mt-1">
                          typed_attribution_exec={robustnessResult.variants.filter((row) => row.attribution_execution_details).length} variants | top_cost_variant={robustnessResult.variants.reduce<{ id: string; cost: number } | null>((best, row) => {
                            const cost = Number(row.attribution_execution_details?.cost_detail.total_cost ?? -Infinity);
                            if (!Number.isFinite(cost)) return best;
                            if (!best || cost > best.cost) return { id: row.variant_id, cost };
                            return best;
                          }, null)?.id ?? "n/a"}
                        </p>
                      ) : null}
                    </>
                  ) : null}
                  {validation && typeof validation.summary === "string" ? (
                    <>
                      <div className="mt-2 flex flex-wrap items-center gap-2">
                        <Badge variant={validationBadgeVariant(validation.status)}>
                          {validation.status}
                        </Badge>
                        <Badge variant="muted">
                          decision={validation.decision_status}
                        </Badge>
                        {compilation && typeof compilation.summary === "string" ? (
                          <Badge variant="muted">
                            overlays={compilation.overlays.length}
                          </Badge>
                        ) : null}
                      </div>
                      <p className="mt-2">{validation.summary}</p>
                      {compilation && typeof compilation.summary === "string" ? (
                        <>
                          <p className="mt-2">compile: {compilation.summary}</p>
                          {compilation.compilation_profile?.summary ? (
                            <p className="mt-2">profile: {compilation.compilation_profile.summary}</p>
                          ) : null}
                          {compilation.compilation_policy?.summary ? (
                            <p className="mt-2">policy: {compilation.compilation_policy.summary}</p>
                          ) : null}
                        </>
                      ) : null}
                    </>
                  ) : (
                    <p className="mt-2">Validation unavailable for this robustness artifact.</p>
                  )}
                      </>
                    );
                  })()}
                </div>
                  );
                })()}
                <div className="grid gap-2 md:grid-cols-4">
                  <div className="rounded-lg border p-3">
                    <p className="text-xs text-muted-foreground">Variant count</p>
                    <p className="text-lg font-semibold">{robustnessResult.summary.variant_count}</p>
                  </div>
                  <div className="rounded-lg border p-3">
                    <p className="text-xs text-muted-foreground">Sharpe Std</p>
                    <p className="text-lg font-semibold">{robustnessResult.summary.sharpe_std}</p>
                  </div>
                  <div className="rounded-lg border p-3">
                    <p className="text-xs text-muted-foreground">Worst MDD</p>
                    <p className="text-lg font-semibold">{robustnessResult.summary.mdd_worst_case}</p>
                  </div>
                  <div className="rounded-lg border p-3">
                    <p className="text-xs text-muted-foreground">Stability score</p>
                    <p className="text-lg font-semibold">{robustnessResult.summary.stability_score}</p>
                  </div>
                </div>
                {robustnessResult.result_details ? (
                  <div className="rounded-lg border border-dashed p-3 text-xs text-muted-foreground">
                    <p className="font-medium text-foreground">Typed result details</p>
                    <p className="mt-1">{robustnessResult.result_details.summary}</p>
                    <p className="mt-1">
                      best_variant={robustnessResult.result_details.best_variant_id ?? "n/a"} | worst_variant={robustnessResult.result_details.worst_variant_id ?? "n/a"} | regimes={robustnessResult.result_details.regime_metric_count} | stress={robustnessResult.result_details.stress_metric_count}
                    </p>
                  </div>
                ) : null}
              </div>
            )}
          </TabsContent>
        </Tabs>
      </CardContent>
    </Card>
  );
}
