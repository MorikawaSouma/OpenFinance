"use client";

import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";

import { EmptyState } from "@/components/common/empty-state";
import { useWorkbench } from "@/components/providers/workbench-provider";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TBody, Td, Th, THead, Tr } from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { api } from "@/lib/api";
import { messages } from "@/lib/messages";
import type { BacktestReport, MultiMarketCompareResponse, RobustnessReport } from "@/lib/types";

function toNum(value: unknown): number | null {
  return typeof value === "number" ? value : null;
}

const MARKET_OPTIONS = ["US", "CN", "JP", "CRYPTO"] as const;
const STRATEGY_FAMILIES = ["trend", "mean_reversion", "value", "risk_parity"] as const;
const REBALANCE_OPTIONS = ["daily", "weekly", "biweekly", "monthly"] as const;

export default function ReportsPage() {
  const { runs, latestPipeline, loadingCore, pushToast, restoreTraceContext, tasks, activeSessionId } = useWorkbench();
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
  const sessionTaskScope = useMemo(() => (activeSessionId || "reports").trim(), [activeSessionId]);

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
      const diffRaw = Array.isArray(result.diff_table) ? result.diff_table : [];
      setMultiMarketResult({
        compare_id: String(result.compare_id ?? ""),
        baseline_market: String(result.baseline_market ?? ""),
        strategy_spec: (result.strategy_spec && typeof result.strategy_spec === "object" ? result.strategy_spec : {}) as Record<string, unknown>,
        rows: rowsRaw as MultiMarketCompareResponse["rows"],
        diff_table: diffRaw as MultiMarketCompareResponse["diff_table"],
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
      const bundle = await restoreTraceContext(traceId);
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
            {loadingCore ? (
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
                  {multiMarketResult.diff_table.map((row, idx) => (
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
            )}
          </TabsContent>
        </Tabs>
      </CardContent>
    </Card>
  );
}
