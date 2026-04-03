"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { EmptyState } from "@/components/common/empty-state";
import { useWorkbenchShellActions, useWorkbenchShellState } from "@/components/providers/workbench-shell-provider";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TBody, Td, Th, THead, Tr } from "@/components/ui/table";
import { api } from "@/lib/api";
import type { BacktestReport } from "@/lib/types";

type EquityPoint = { x: number; equity: number; drawdown: number };

function toPct(v: unknown) {
  if (typeof v !== "number") return "-";
  return `${(v * 100).toFixed(2)}%`;
}

function cellClass(v: number) {
  if (v >= 0.03) return "bg-success/30";
  if (v > 0) return "bg-success/15";
  if (v <= -0.03) return "bg-destructive/30";
  if (v < 0) return "bg-destructive/15";
  return "bg-muted/10";
}

function validationBadgeVariant(status: string) {
  if (status === "invalid") return "destructive" as const;
  if (status === "warn") return "warning" as const;
  return "success" as const;
}

function compilePolicyBadgeVariant(status: string) {
  if (status === "blocked") return "destructive" as const;
  if (status === "allowed_with_warning") return "warning" as const;
  return "success" as const;
}

function formatCompilePolicyToken(value: string) {
  return value.replace(/_/g, " ");
}

function formatCompileValue(value: unknown) {
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  if (value == null) return "null";
  try {
    const text = JSON.stringify(value);
    return text.length > 120 ? `${text.slice(0, 117)}...` : text;
  } catch {
    return "[unserializable]";
  }
}

function summarizeNumericMap(value: Record<string, number> | undefined, limit = 4) {
  if (!value) return "-";
  const rows = Object.entries(value)
    .sort((a, b) => Math.abs(b[1]) - Math.abs(a[1]))
    .slice(0, limit);
  if (rows.length === 0) return "-";
  return rows.map(([key, number]) => `${key}=${number.toFixed(4)}`).join(" | ");
}

function parseEvidenceRef(ref: string, packId: string | null): { href: string; label: string; external: boolean } {
  if (ref.startsWith("evidence_pack:")) {
    const id = ref.slice("evidence_pack:".length);
    return {
      href: `/evidence?pack=${encodeURIComponent(id)}`,
      label: `Evidence Pack ${id}`,
      external: false,
    };
  }
  if (ref.startsWith("evidence_source:")) {
    const id = ref.slice("evidence_source:".length);
    const query = new URLSearchParams();
    if (packId) query.set("pack", packId);
    query.set("source", id);
    return {
      href: `/evidence?${query.toString()}`,
      label: `Evidence Source ${id}`,
      external: false,
    };
  }
  return {
    href: ref,
    label: ref,
    external: /^https?:\/\//i.test(ref),
  };
}

export default function ReportDetailPage() {
  const params = useParams<{ runId: string }>();
  const runId = String(params.runId ?? "");
  const { mode } = useWorkbenchShellState();
  const { pushToast } = useWorkbenchShellActions();
  const [loading, setLoading] = useState(true);
  const [report, setReport] = useState<BacktestReport | null>(null);
  const [tradeSideFilter, setTradeSideFilter] = useState<"all" | "buy" | "sell">("all");
  const [tradeInstrumentFilter, setTradeInstrumentFilter] = useState("");
  const [tradeSort, setTradeSort] = useState<"time_desc" | "time_asc" | "commission_desc" | "slippage_desc" | "qty_desc">("time_desc");

  const load = useCallback(async () => {
    if (!runId) return;
    setLoading(true);
    try {
      setReport(await api.getRun(runId));
    } catch (err) {
      setReport(null);
      pushToast("Load report failed", err instanceof Error ? err.message : "Unknown error", "error");
    } finally {
      setLoading(false);
    }
  }, [pushToast, runId]);

  useEffect(() => {
    void load();
  }, [load]);

  const series = (report?.diagnostics?.series ?? {}) as {
    equity_curve?: EquityPoint[];
    monthly_returns?: Record<string, number>;
  };
  const runtimeSummary = report?.runtime_summary ?? null;
  const runtimeDiagnostics = report?.runtime_diagnostics ?? null;
  const actionRegimeDetails = report?.action_regime_details ?? null;
  const attributionExecutionDetails = report?.attribution_execution_details ?? null;
  const controlOptimizerDetails = report?.control_optimizer_details ?? null;
  const controlActionDeepDetails = report?.control_action_deep_details ?? null;
  const regimePeriods = actionRegimeDetails?.regime_periods ?? (
    Array.isArray(report?.diagnostics?.regime_periods)
      ? (report?.diagnostics?.regime_periods as Array<Record<string, unknown>>)
      : []
  );
  const riskActions = actionRegimeDetails?.risk_actions ?? (
    Array.isArray(report?.diagnostics?.risk_actions)
      ? (report?.diagnostics?.risk_actions as Array<Record<string, unknown>>)
      : []
  );
  const constraintActions = actionRegimeDetails?.constraint_actions ?? [];
  const failureConditionEvents = actionRegimeDetails?.failure_condition_events ?? [];
  const rejectedOrders = controlOptimizerDetails?.rejected_orders ?? (
    Array.isArray(report?.diagnostics?.rejected_orders)
      ? (report?.diagnostics?.rejected_orders as Array<Record<string, unknown>>)
      : []
  );
  const optimizerDiagnostics = controlOptimizerDetails?.optimizer_diagnostics ?? (
    Array.isArray(report?.diagnostics?.optimizer_diagnostics)
      ? (report?.diagnostics?.optimizer_diagnostics as Array<Record<string, unknown>>)
      : []
  );
  const circuitBreakerIntervals = controlOptimizerDetails?.circuit_breaker_intervals ?? (
    Array.isArray(
      ((report?.diagnostics?.risk_management as Record<string, unknown> | undefined)?.circuit_breaker as Record<string, unknown> | undefined)?.trigger_intervals
    )
      ? ((((report?.diagnostics?.risk_management as Record<string, unknown> | undefined)?.circuit_breaker as Record<string, unknown> | undefined)?.trigger_intervals) as Array<Record<string, unknown>>)
      : []
  );
  const riskContributionPoints = controlOptimizerDetails?.risk_contribution_points ?? (
    Array.isArray(report?.diagnostics?.risk_contribution_ts)
      ? (report?.diagnostics?.risk_contribution_ts as Array<Record<string, unknown>>)
      : []
  );
  const budgetDetail = controlOptimizerDetails?.budget_detail ?? {
    mean_l1: runtimeDiagnostics?.budget_deviation.mean_l1 ?? null,
    max_l1: runtimeDiagnostics?.budget_deviation.max_l1 ?? null,
    observations: runtimeDiagnostics?.budget_deviation.observations ?? 0,
    latest_time: null,
    latest_deviation_l1: null,
    latest_target_budget: {},
    latest_achieved_budget: {},
  };
  const deepOptimizerSteps = controlActionDeepDetails?.optimizer_steps ?? [];
  const circuitBreakerState = controlActionDeepDetails?.circuit_breaker_state ?? {
    enabled: null,
    rule_type: null,
    threshold: null,
    trigger_count: 0,
    stop_trading_triggered: null,
    execution_support: {
      drawdown: null,
      consecutive_losses: null,
      vol_spike: null,
    },
    intervals: [],
  };
  const budgetBreakdown = controlActionDeepDetails?.budget_breakdown ?? {
    mean_l1: null,
    max_l1: null,
    observations: 0,
    latest_time: null,
    latest_deviation_l1: null,
    latest_gap_by_asset: {},
    peak_time: null,
    peak_deviation_l1: null,
    peak_gap_by_asset: {},
  };
  const riskContributionBreakdown = controlActionDeepDetails?.risk_contribution_breakdown ?? {
    point_count: 0,
    latest: null,
    peak: null,
  };
  const topLevelCurve = Array.isArray(report?.equity_curve)
    ? (report?.equity_curve as EquityPoint[])
    : [];
  const equityCurve = Array.isArray(series.equity_curve) && series.equity_curve.length > 0
    ? series.equity_curve
    : topLevelCurve;
  const monthlyRows = Object.entries(series.monthly_returns ?? {});
  const evidencePackRef = report?.evidence_refs.find((ref) => ref.startsWith("evidence_pack:")) ?? null;
  const evidencePackId = evidencePackRef ? evidencePackRef.slice("evidence_pack:".length) : null;
  const factorVersions = Array.isArray(report?.factor_versions) ? report.factor_versions : [];
  const factorVersionsReason = report?.factor_versions_reason ?? null;
  const strategyDecision = report?.strategy_decision ?? null;
  const strategyValidation = report?.strategy_validation ?? null;
  const strategyCompilation = report?.strategy_compilation ?? null;
  const strategyTrace = report?.strategy_trace ?? null;
  const runtimeMetrics = runtimeSummary?.metrics ?? null;
  const strategyTraceEvaluationPlan = strategyTrace?.evaluation_plan ?? null;
  const strategyTraceFactorLineage = strategyTrace?.factor_lineage ?? null;
  const strategyDecisionSelected = strategyDecision?.selected ?? null;
  const strategyDecisionCandidates = strategyDecision?.candidates ?? [];
  const hasStrategyDecision = Boolean(strategyDecisionSelected?.name || strategyDecisionCandidates.length > 0);
  const reportCostBreakdown = report?.cost_breakdown;
  const reportMetrics = report?.metrics;
  const reportOrders = report?.orders ?? [];
  const reportTrades = report?.trades ?? [];
  const costDetail = attributionExecutionDetails?.cost_detail ?? {
    commission_sum: reportCostBreakdown?.commission_sum ?? reportCostBreakdown?.commission ?? 0,
    slippage_sum: reportCostBreakdown?.slippage_sum ?? reportCostBreakdown?.slippage ?? 0,
    total_cost: reportCostBreakdown?.total ?? 0,
    trade_count: reportTrades.length,
    order_count: reportOrders.length,
    avg_total_cost_per_trade: reportTrades.length > 0 ? (Number(reportCostBreakdown?.total ?? 0) / reportTrades.length) : null,
    avg_total_cost_per_order: reportOrders.length > 0 ? (Number(reportCostBreakdown?.total ?? 0) / reportOrders.length) : null,
    cost_drag:
      typeof runtimeMetrics?.cost_drag === "number"
        ? runtimeMetrics.cost_drag
        : typeof reportMetrics?.cost_drag === "number"
          ? reportMetrics.cost_drag
          : null,
  };
  const executionStyleDetail = attributionExecutionDetails?.execution_style_detail ?? {
    execution_model: runtimeDiagnostics?.execution_model ?? null,
    order_count: reportOrders.length,
    filled_order_count: reportOrders.filter((row) => row.status === "filled").length,
    rejected_order_count: reportOrders.filter((row) => row.status === "rejected").length,
    queued_order_count: reportOrders.filter((row) => row.status === "queued").length,
    trade_count: reportTrades.length,
    buy_trade_count: reportTrades.filter((row) => row.side.toLowerCase() === "buy").length,
    sell_trade_count: reportTrades.filter((row) => row.side.toLowerCase() === "sell").length,
    fill_rate: reportOrders.length > 0 ? reportOrders.filter((row) => row.status === "filled").length / reportOrders.length : null,
    avg_trade_qty: reportTrades.length > 0 ? reportTrades.reduce((sum, row) => sum + row.qty, 0) / reportTrades.length : null,
    order_status_counts: {},
    reject_reason_counts: {},
    dominant_reject_reason: null,
  };

  const keyMetrics = useMemo(() => {
    if (!report) return [];
    return [
      ["total_return", runtimeMetrics?.total_return ?? report.metrics.total_return],
      ["sharpe", runtimeMetrics?.sharpe ?? report.metrics.sharpe],
      ["max_drawdown", runtimeMetrics?.max_drawdown ?? report.metrics.max_drawdown],
      ["volatility", runtimeMetrics?.volatility ?? report.metrics.volatility],
      ["trade_count", runtimeMetrics?.trade_count ?? report.metrics.trade_count],
      ["risk_scale", runtimeMetrics?.risk_scale ?? report.metrics.risk_scale],
    ];
  }, [report, runtimeMetrics]);

  const tradesView = useMemo(() => {
    if (!report) return [];
    let rows = report.trades.slice();
    if (tradeSideFilter !== "all") {
      rows = rows.filter((row) => row.side.toLowerCase() === tradeSideFilter);
    }
    if (tradeInstrumentFilter.trim()) {
      const pattern = tradeInstrumentFilter.trim().toLowerCase();
      rows = rows.filter((row) => row.instrument.toLowerCase().includes(pattern));
    }
    rows.sort((a, b) => {
      if (tradeSort === "time_asc") return new Date(a.time).getTime() - new Date(b.time).getTime();
      if (tradeSort === "commission_desc") return b.commission - a.commission;
      if (tradeSort === "slippage_desc") return b.slippage - a.slippage;
      if (tradeSort === "qty_desc") return b.qty - a.qty;
      return new Date(b.time).getTime() - new Date(a.time).getTime();
    });
    return rows.slice(0, 100);
  }, [report, tradeInstrumentFilter, tradeSideFilter, tradeSort]);

  const instrumentAttribution = useMemo(
    () =>
      attributionExecutionDetails?.attribution_detail.instrument_rows ??
      Object.entries(report?.attribution?.instrument_pnl_contrib ?? {}).map(([label, pnl]) => ({
        label,
        pnl: Number(pnl),
        abs_share: null,
      })),
    [attributionExecutionDetails, report]
  );
  const sectorAttribution = useMemo(
    () =>
      attributionExecutionDetails?.attribution_detail.sector_rows ??
      Object.entries(report?.attribution?.sector_pnl_contrib ?? {}).map(([label, pnl]) => ({
        label,
        pnl: Number(pnl),
        abs_share: null,
      })),
    [attributionExecutionDetails, report]
  );

  function copyRunLink() {
    const url = `${window.location.origin}/reports/${runId}`;
    navigator.clipboard
      .writeText(url)
      .then(() => pushToast("Run link copied", url, "success"))
      .catch(() => pushToast("Copy failed", "Clipboard is unavailable.", "error"));
  }

  if (loading) {
    return (
      <div className="grid gap-4">
        <Skeleton className="h-28 w-full" />
        <Skeleton className="h-72 w-full" />
        <Skeleton className="h-72 w-full" />
      </div>
    );
  }

  if (!report) {
    return <EmptyState title="Report not found" description="This run may not exist. Retry or run backtest again." />;
  }

  return (
    <div className="grid gap-4">
      <Card>
        <CardHeader>
          <div>
            <CardTitle>Run Summary</CardTitle>
            <CardDescription>Conclusion, actions, and reproducible report context.</CardDescription>
          </div>
          <div className="flex gap-2">
            <Button variant="outline" onClick={() => void load()}>
              Retry
            </Button>
            <Button variant="secondary" onClick={copyRunLink}>
              Copy Run Link
            </Button>
            <Link href="/reports">
              <Button>Back to Reports</Button>
            </Link>
          </div>
        </CardHeader>
        <div className="grid gap-2 text-sm md:grid-cols-2">
          <p>run_id: <span className="font-medium">{report.run_id}</span></p>
          <p>dataset_version: <span className="font-medium">{report.dataset_version}</span></p>
          <p>market: <span className="font-medium">{String(report.market ?? "-")}</span></p>
          <p>strategy_version: <span className="font-medium">{report.strategy_version}</span></p>
          <p>strategy_decision_selected: <span className="font-medium">{String(strategyDecisionSelected?.name ?? "n/a")}</span></p>
          <p>created_at: <span className="font-medium">{new Date(report.created_at).toLocaleString()}</span></p>
          {runtimeSummary ? (
            <>
              <p>runtime_summary: <span className="font-medium">{runtimeSummary.summary}</span></p>
              <p>compile_ready: <span className="font-medium">{runtimeSummary.compile_ready == null ? "n/a" : runtimeSummary.compile_ready ? "true" : "false"}</span></p>
              <p>evidence_ref_count: <span className="font-medium">{runtimeSummary.evidence_ref_count}</span></p>
              <p>factor_lineage_count: <span className="font-medium">{runtimeSummary.factor_lineage_count}</span></p>
            </>
          ) : null}
          {runtimeDiagnostics ? (
            <>
              <p>execution_model: <span className="font-medium">{runtimeDiagnostics.execution_model || "n/a"}</span></p>
              <p>optimizer: <span className="font-medium">{runtimeDiagnostics.portfolio_optimization.optimizer ?? "n/a"}</span></p>
              <p>risk_action_count: <span className="font-medium">{runtimeDiagnostics.action_counts.risk_action_count}</span></p>
              <p>rejected_orders: <span className="font-medium">{runtimeDiagnostics.action_counts.rejected_order_count}</span></p>
            </>
          ) : null}
          <div className="md:col-span-2">
            <p className="mb-1">
              factor_versions:{" "}
              <span className="font-medium">
                {factorVersions.length > 0 ? `${factorVersions.length} linked` : "none"}
              </span>
            </p>
            {factorVersions.length > 0 ? (
              <div className="flex flex-wrap gap-1">
                {factorVersions.map((row, idx) => (
                  <Badge key={`${row.factor_id}-${row.version}-${idx}`} variant="muted">
                    {row.factor_id}@{row.version}
                  </Badge>
                ))}
              </div>
            ) : (
              <p className="text-xs text-muted-foreground">
                reason: {factorVersionsReason ?? "not_provided"}
              </p>
            )}
          </div>
        </div>
        <div className="mt-3 flex flex-wrap gap-2">
          <Badge variant="success">Action: Keep low-drawdown constraints enabled</Badge>
          <Badge variant="muted">Action: Review monthly drawdown clusters</Badge>
          <Badge variant="warning">Action: Validate with higher cost sensitivity</Badge>
        </div>
        {mode === "developer" ? (
          <p className="mt-2 text-xs text-muted-foreground">internal trace: {report.audit_trace_id}</p>
        ) : null}
      </Card>

      {hasStrategyDecision ? (
        <Card>
          <CardHeader>
            <div>
              <CardTitle>Strategy Decision</CardTitle>
              <CardDescription>
                Typed decision artifact. `StrategyDecision` records candidate trade-offs; `BacktestRequest` remains the executable runtime object.
              </CardDescription>
            </div>
          </CardHeader>
          <div className="grid gap-3 text-sm xl:grid-cols-2">
            <div className="rounded-lg border p-3">
              <p>selected: <span className="font-medium">{String(strategyDecisionSelected?.name ?? "-")}</span></p>
              <p className="mt-2 text-xs text-muted-foreground whitespace-pre-wrap">
                {String(strategyDecisionSelected?.rationale ?? "No rationale provided.")}
              </p>
              <p className="mt-2 text-xs text-muted-foreground whitespace-pre-wrap">
                {String(strategyDecisionSelected?.tradeoff_summary ?? "No trade-off summary provided.")}
              </p>
              <div className="mt-3 grid gap-2 rounded-lg border border-dashed p-3 text-xs md:grid-cols-2">
                <p>strategy_family: <span className="font-medium">{strategyDecisionSelected?.spec.strategy_family ?? "-"}</span></p>
                <p>rebalance: <span className="font-medium">{strategyDecisionSelected?.spec.rebalance ?? "-"}</span></p>
                <p>lookback_days: <span className="font-medium">{String(strategyDecisionSelected?.spec.lookback_days ?? "-")}</span></p>
                <p>position_sizing: <span className="font-medium">{strategyDecisionSelected?.spec.position_sizing ?? "-"}</span></p>
                <p>risk_budget: <span className="font-medium">{strategyDecisionSelected?.spec.risk_budget ?? "-"}</span></p>
                <p>max_position: <span className="font-medium">{String(strategyDecisionSelected?.spec.max_position ?? "-")}</span></p>
              </div>
            </div>
            <Table>
              <THead>
                <tr>
                  <Th>Candidate</Th>
                  <Th>Spec</Th>
                  <Th>Cost Profile</Th>
                  <Th>Why Not Selected</Th>
                </tr>
              </THead>
              <TBody>
                {strategyDecisionCandidates.length === 0 ? (
                  <Tr>
                    <Td>-</Td>
                    <Td>-</Td>
                    <Td>-</Td>
                    <Td>No candidate records</Td>
                  </Tr>
                ) : (
                  strategyDecisionCandidates.slice(0, 4).map((row, idx) => (
                    <Tr key={`decision-candidate-${idx}`}>
                      <Td>{String(row.name ?? "-")}</Td>
                      <Td>{`${row.spec.strategy_family}/${row.spec.position_sizing}/${row.spec.rebalance}`}</Td>
                      <Td>{String(row.cost_profile ?? "-")}</Td>
                      <Td>{String(row.why_not_selected ?? "-")}</Td>
                    </Tr>
                  ))
                )}
              </TBody>
            </Table>
          </div>
        </Card>
      ) : null}

      {strategyValidation ? (
        <Card>
          <CardHeader>
            <div>
              <CardTitle>Strategy Validation</CardTitle>
              <CardDescription>
                Validation artifact for the durable `StrategySpec` before it compiled into the runtime `BacktestRequest`.
              </CardDescription>
            </div>
          </CardHeader>
          <div className="grid gap-3 text-sm xl:grid-cols-2">
            <div className="rounded-lg border p-3">
              <div className="flex flex-wrap items-center gap-2">
                <Badge variant={validationBadgeVariant(strategyValidation.status)}>{strategyValidation.status}</Badge>
                <Badge variant="muted">decision={strategyValidation.decision_status}</Badge>
                <Badge variant="muted">next={strategyValidation.next_output}</Badge>
              </div>
              <p className="mt-3 text-xs text-muted-foreground whitespace-pre-wrap">
                {strategyValidation.summary}
              </p>
              <div className="mt-3 grid gap-2 rounded-lg border border-dashed p-3 text-xs md:grid-cols-2">
                <p>compile_ready: <span className="font-medium">{strategyValidation.compile_ready ? "true" : "false"}</span></p>
                <p>selected_candidate: <span className="font-medium">{strategyValidation.selected_candidate ?? "n/a"}</span></p>
                <p>validated_object: <span className="font-medium">{strategyValidation.validated_object}</span></p>
                <p>evidence_refs: <span className="font-medium">{strategyValidation.evidence_refs.length}</span></p>
              </div>
            </div>
            <Table>
              <THead>
                <tr>
                  <Th>Check</Th>
                  <Th>Status</Th>
                  <Th>Detail</Th>
                </tr>
              </THead>
              <TBody>
                {strategyValidation.checks.map((check) => (
                  <Tr key={`validation-check-${check.check_id}`}>
                    <Td>{check.check_id}</Td>
                    <Td>
                      <Badge variant={validationBadgeVariant(check.status)}>{check.status}</Badge>
                    </Td>
                    <Td>{check.detail}</Td>
                  </Tr>
                ))}
              </TBody>
            </Table>
          </div>
        </Card>
      ) : null}

      {strategyCompilation ? (
        <Card>
          <CardHeader>
            <div>
              <CardTitle>Strategy Compilation</CardTitle>
              <CardDescription>
                Typed source map from validated strategy semantics into the executable `BacktestRequest`.
              </CardDescription>
            </div>
          </CardHeader>
          <div className="grid gap-3 text-sm xl:grid-cols-2">
            <div className="rounded-lg border p-3">
              <div className="flex flex-wrap items-center gap-2">
                <Badge variant={validationBadgeVariant(strategyCompilation.validation_status)}>
                  {strategyCompilation.validation_status}
                </Badge>
                <Badge variant="muted">target={strategyCompilation.executable_object}</Badge>
                <Badge variant="muted">decision={strategyCompilation.decision_status}</Badge>
                {strategyCompilation.compilation_policy ? (
                  <Badge variant={compilePolicyBadgeVariant(strategyCompilation.compilation_policy.status)}>
                    policy={strategyCompilation.compilation_policy.status}
                  </Badge>
                ) : null}
              </div>
              <p className="mt-3 text-xs whitespace-pre-wrap text-muted-foreground">
                {strategyCompilation.summary}
              </p>
              <div className="mt-3 grid gap-2 rounded-lg border border-dashed p-3 text-xs md:grid-cols-2">
                <p>compile_ready: <span className="font-medium">{strategyCompilation.compile_ready ? "true" : "false"}</span></p>
                <p>selected_candidate: <span className="font-medium">{strategyCompilation.selected_candidate ?? "n/a"}</span></p>
                <p>bindings: <span className="font-medium">{strategyCompilation.bindings.length}</span></p>
                <p>overlays: <span className="font-medium">{strategyCompilation.overlays.length}</span></p>
              </div>
              {strategyCompilation.compilation_profile ? (
                <div className="mt-3 rounded-lg border border-dashed p-3 text-xs text-muted-foreground">
                  <p className="font-medium uppercase tracking-wide text-foreground">Compile Profile</p>
                  <p className="mt-2 whitespace-pre-wrap">{strategyCompilation.compilation_profile.summary}</p>
                  <div className="mt-2 flex flex-wrap gap-2">
                    {(["user_configurable", "environment_bound", "runtime_derived", "validation_required_override"] as const).map((kind) => {
                      const count = strategyCompilation.compilation_profile?.input_policies.filter((row) => row.classification === kind).length ?? 0;
                      return (
                        <Badge key={kind} variant="muted">
                          {formatCompilePolicyToken(kind)}={count}
                        </Badge>
                      );
                    })}
                  </div>
                </div>
              ) : null}
              {strategyCompilation.compilation_policy ? (
                <div className="mt-3 rounded-lg border border-dashed p-3 text-xs text-muted-foreground">
                  <p className="font-medium uppercase tracking-wide text-foreground">Compile Policy</p>
                  <p className="mt-2 whitespace-pre-wrap">{strategyCompilation.compilation_policy.summary}</p>
                  <p className="mt-2">
                    rule_surface={strategyCompilation.compilation_policy.rule_surface_id}
                  </p>
                  <div className="mt-2 flex flex-wrap gap-2">
                    <Badge variant={compilePolicyBadgeVariant(strategyCompilation.compilation_policy.status)}>
                      {strategyCompilation.compilation_policy.status}
                    </Badge>
                    <Badge variant="muted">
                      allowed={Math.max(
                        0,
                        strategyCompilation.compilation_policy.checks.length
                          - strategyCompilation.compilation_policy.warning_count
                          - strategyCompilation.compilation_policy.blocked_count,
                      )}
                    </Badge>
                    <Badge variant="muted">warning={strategyCompilation.compilation_policy.warning_count}</Badge>
                    <Badge variant="muted">blocked={strategyCompilation.compilation_policy.blocked_count}</Badge>
                  </div>
                </div>
              ) : null}
              {strategyTrace ? (
                <div className="mt-3 rounded-lg border border-dashed p-3 text-xs text-muted-foreground">
                  <p className="font-medium uppercase tracking-wide text-foreground">Report Trace Boundary</p>
                  <p className="mt-2 whitespace-pre-wrap">{strategyTrace.summary}</p>
                  <div className="mt-3 grid gap-2 rounded-lg border border-dashed p-3 md:grid-cols-2">
                    <p>trace_object: <span className="font-medium">{strategyTrace.trace_object}</span></p>
                    <p>evaluation_plan: <span className="font-medium">{strategyTraceEvaluationPlan?.schema_version ?? "n/a"}</span></p>
                    <p>factor_lineage: <span className="font-medium">{strategyTraceFactorLineage?.factor_versions.length ?? 0}</span></p>
                    <p>evidence_refs: <span className="font-medium">{strategyTraceEvaluationPlan?.evidence_refs.length ?? 0}</span></p>
                  </div>
                  {strategyTraceFactorLineage?.reason ? (
                    <p className="mt-2">
                      factor_lineage_reason: <span className="font-medium">{strategyTraceFactorLineage.reason}</span>
                    </p>
                  ) : null}
                </div>
              ) : null}
            </div>
            <div className="space-y-3">
              {strategyCompilation.compilation_profile ? (
                <Table>
                  <THead>
                    <tr>
                      <Th>Config Path</Th>
                      <Th>Class</Th>
                      <Th>Configured By</Th>
                    </tr>
                  </THead>
                  <TBody>
                    {strategyCompilation.compilation_profile.input_policies.slice(0, 10).map((row) => (
                      <Tr key={`compilation-policy-${row.output_path}-${row.source_path}`}>
                        <Td>{row.output_path}</Td>
                        <Td>{formatCompilePolicyToken(row.classification)}</Td>
                        <Td>{formatCompilePolicyToken(row.configured_by)}</Td>
                      </Tr>
                    ))}
                  </TBody>
                </Table>
              ) : null}
              <Table>
                <THead>
                  <tr>
                    <Th>Output Path</Th>
                    <Th>Source</Th>
                    <Th>Value</Th>
                  </tr>
                </THead>
                <TBody>
                  {strategyCompilation.bindings.slice(0, 12).map((row) => (
                    <Tr key={`compilation-binding-${row.output_path}-${row.source_path}`}>
                      <Td>{row.output_path}</Td>
                      <Td>{`${row.source_kind}:${row.source_path}`}</Td>
                      <Td>{formatCompileValue(row.value)}</Td>
                    </Tr>
                  ))}
                </TBody>
              </Table>
              {strategyCompilation.compilation_policy ? (
                <Table>
                  <THead>
                    <tr>
                      <Th>Policy Path</Th>
                      <Th>Outcome</Th>
                      <Th>Rule</Th>
                    </tr>
                  </THead>
                  <TBody>
                    {(strategyCompilation.compilation_policy.checks.some((row) => row.outcome !== "allowed")
                      ? strategyCompilation.compilation_policy.checks.filter((row) => row.outcome !== "allowed")
                      : strategyCompilation.compilation_policy.checks.slice(0, 4)
                    ).map((row) => (
                      <Tr key={`compilation-policy-check-${row.code}-${row.output_path}`}>
                        <Td>{row.output_path}</Td>
                        <Td>{formatCompilePolicyToken(row.outcome)}</Td>
                        <Td>{row.rule_id}</Td>
                      </Tr>
                    ))}
                  </TBody>
                </Table>
              ) : null}
            </div>
          </div>
          <div className="mt-3 space-y-2">
            <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Compile-Time Overlays</p>
            {strategyCompilation.overlays.length > 0 ? (
              strategyCompilation.overlays.map((row) => (
                <div key={`compilation-overlay-${row.output_path}-${row.source_path}`} className="rounded-lg border p-3 text-xs text-muted-foreground">
                  <p className="font-medium text-foreground">{row.output_path}</p>
                  <p className="mt-1">final={formatCompileValue(row.final_value)}</p>
                  <p className="mt-1">source={row.source_kind} / {row.source_path}</p>
                  {row.overridden_source_path ? (
                    <p className="mt-1">
                      overrides={row.overridden_source_kind} / {row.overridden_source_path} ({formatCompileValue(row.overridden_value)})
                    </p>
                  ) : null}
                  <p className="mt-1">{row.rationale}</p>
                </div>
              ))
            ) : (
              <div className="rounded-lg border border-dashed p-3 text-xs text-muted-foreground">
                No compile-time overlays were recorded for this run.
              </div>
            )}
            {strategyCompilation.compilation_profile?.override_policies.length ? (
              <div className="space-y-2 pt-2">
                <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Override Policy</p>
                {strategyCompilation.compilation_profile.override_policies.map((row) => (
                  <div key={`override-policy-${row.output_path}-${row.source_path}`} className="rounded-lg border p-3 text-xs text-muted-foreground">
                    <p className="font-medium text-foreground">{row.output_path}</p>
                    <p className="mt-1">
                      class={formatCompilePolicyToken(row.classification)} / configured_by={formatCompilePolicyToken(row.configured_by)}
                    </p>
                    <p className="mt-1">
                      source={row.source_kind}:{row.source_path} / requires_validation={row.requires_additional_validation ? "true" : "false"}
                    </p>
                    <p className="mt-1">{row.rationale}</p>
                  </div>
                ))}
              </div>
            ) : null}
            {strategyCompilation.compilation_policy ? (
              <div className="space-y-2 pt-2">
                <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Compile Policy Checks</p>
                {(strategyCompilation.compilation_policy.checks.some((row) => row.outcome !== "allowed")
                  ? strategyCompilation.compilation_policy.checks.filter((row) => row.outcome !== "allowed")
                  : strategyCompilation.compilation_policy.checks.slice(0, 4)
                ).map((row) => (
                  <div key={`compile-policy-check-${row.code}-${row.output_path}`} className="rounded-lg border p-3 text-xs text-muted-foreground">
                    <div className="flex flex-wrap items-center gap-2">
                      <Badge variant={compilePolicyBadgeVariant(row.outcome)}>{row.outcome}</Badge>
                      <span className="font-medium text-foreground">{row.output_path}</span>
                    </div>
                    <p className="mt-1">
                      rule={row.rule_id} / code={row.code}
                    </p>
                    <p className="mt-1">
                      fact={formatCompilePolicyToken(row.fact_source)} / checked_by={formatCompilePolicyToken(row.checked_by)}
                    </p>
                    <p className="mt-1">
                      class={formatCompilePolicyToken(row.classification)} / configured_by={formatCompilePolicyToken(row.configured_by)}
                    </p>
                    <p className="mt-1">
                      requires_validation={row.requires_additional_validation ? "true" : "false"}
                    </p>
                    <p className="mt-1">{row.detail}</p>
                  </div>
                ))}
              </div>
            ) : null}
          </div>
        </Card>
      ) : null}

      <Card>
        <CardHeader>
          <div>
            <CardTitle>Backtest Metrics</CardTitle>
            <CardDescription>Standardized metrics table.</CardDescription>
          </div>
        </CardHeader>
        <Table>
          <THead>
            <tr>
              <Th>Metric</Th>
              <Th>Value</Th>
            </tr>
          </THead>
          <TBody>
            {keyMetrics.map(([k, v]) => (
              <Tr key={k}>
                <Td>{k}</Td>
                <Td>{String(v ?? "-")}</Td>
              </Tr>
            ))}
          </TBody>
        </Table>
      </Card>

      <Card>
        <CardHeader>
          <div>
            <CardTitle>Cost Breakdown</CardTitle>
            <CardDescription>Typed cost and execution-style detail from actual orders and fills.</CardDescription>
          </div>
        </CardHeader>
        <div className="grid gap-3 text-sm md:grid-cols-3">
          {attributionExecutionDetails ? (
            <div className="md:col-span-3 rounded-lg border border-dashed p-3 text-xs text-muted-foreground">
              <p className="font-medium text-foreground">Typed attribution / execution detail</p>
              <p className="mt-1">{attributionExecutionDetails.summary || "Using typed attribution/execution detail rows from current report payload."}</p>
              <p className="mt-1">
                execution_model={executionStyleDetail.execution_model ?? "n/a"} | fill_rate={executionStyleDetail.fill_rate == null ? "n/a" : executionStyleDetail.fill_rate.toFixed(4)} | dominant_reject={executionStyleDetail.dominant_reject_reason ?? "n/a"}
              </p>
            </div>
          ) : null}
          <p>commission_sum: <span className="font-medium">{String(costDetail.commission_sum ?? 0)}</span></p>
          <p>slippage_sum: <span className="font-medium">{String(costDetail.slippage_sum ?? 0)}</span></p>
          <p>total cost: <span className="font-medium">{String(costDetail.total_cost ?? 0)}</span></p>
          <p>avg / trade: <span className="font-medium">{String(costDetail.avg_total_cost_per_trade ?? "n/a")}</span></p>
          <p>avg / order: <span className="font-medium">{String(costDetail.avg_total_cost_per_order ?? "n/a")}</span></p>
          <p>cost_drag: <span className="font-medium">{String(costDetail.cost_drag ?? "n/a")}</span></p>
          <p>trade_count: <span className="font-medium">{String(costDetail.trade_count)}</span></p>
          <p>order_count: <span className="font-medium">{String(costDetail.order_count)}</span></p>
          <p>filled/rejected/queued: <span className="font-medium">{`${executionStyleDetail.filled_order_count}/${executionStyleDetail.rejected_order_count}/${executionStyleDetail.queued_order_count}`}</span></p>
          <p>buy/sell trades: <span className="font-medium">{`${executionStyleDetail.buy_trade_count}/${executionStyleDetail.sell_trade_count}`}</span></p>
          <p>avg trade qty: <span className="font-medium">{String(executionStyleDetail.avg_trade_qty ?? "n/a")}</span></p>
          <p>reject reason counts: <span className="font-medium">{Object.entries(executionStyleDetail.reject_reason_counts).length > 0 ? Object.entries(executionStyleDetail.reject_reason_counts).map(([key, value]) => `${key}=${value}`).join(" | ") : "n/a"}</span></p>
        </div>
      </Card>

      <Card>
        <CardHeader>
          <div>
            <CardTitle>Attribution</CardTitle>
            <CardDescription>Instrument and sector PnL contribution.</CardDescription>
          </div>
        </CardHeader>
        {instrumentAttribution.length === 0 ? (
          <EmptyState title="No attribution rows" description="No fills were generated for attribution." />
        ) : (
          <div className="grid gap-4 xl:grid-cols-2">
            <Table>
              <THead>
              <tr>
                <Th>Instrument</Th>
                <Th>PnL Contrib</Th>
                <Th>Abs Share</Th>
              </tr>
            </THead>
            <TBody>
                {instrumentAttribution.map((row) => (
                  <Tr key={row.label}>
                    <Td>{row.label}</Td>
                    <Td>{String(row.pnl)}</Td>
                    <Td>{row.abs_share == null ? "-" : row.abs_share.toFixed(4)}</Td>
                  </Tr>
                ))}
              </TBody>
            </Table>
            <Table>
              <THead>
                <tr>
                  <Th>Sector</Th>
                  <Th>PnL Contrib</Th>
                  <Th>Abs Share</Th>
                </tr>
              </THead>
              <TBody>
                {(sectorAttribution.length > 0 ? sectorAttribution : [{ label: "Unknown", pnl: 0, abs_share: null }]).map((row) => (
                  <Tr key={row.label}>
                    <Td>{row.label}</Td>
                    <Td>{String(row.pnl)}</Td>
                    <Td>{row.abs_share == null ? "-" : row.abs_share.toFixed(4)}</Td>
                  </Tr>
                ))}
              </TBody>
            </Table>
          </div>
        )}
      </Card>

      <Card>
        <CardHeader>
          <div>
            <CardTitle>Regime And Risk Actions</CardTitle>
            <CardDescription>Volatility regime windows and RiskManager actions in backtest loop.</CardDescription>
          </div>
        </CardHeader>
        <div className="grid gap-4 xl:grid-cols-2">
          {runtimeDiagnostics ? (
            <div className="xl:col-span-2 rounded-lg border border-dashed p-3 text-xs text-muted-foreground">
              <p className="font-medium text-foreground">Typed runtime diagnostics</p>
              <p className="mt-1">{runtimeDiagnostics.summary || "No runtime diagnostics summary available."}</p>
              <p className="mt-1">
                execution_model={runtimeDiagnostics.execution_model || "n/a"} | optimizer={runtimeDiagnostics.portfolio_optimization.optimizer ?? "n/a"} | risk_actions={runtimeDiagnostics.action_counts.risk_action_count} | regime_periods={runtimeDiagnostics.action_counts.regime_period_count}
              </p>
              <p className="mt-1">
                rejected_orders={runtimeDiagnostics.action_counts.rejected_order_count} | constraint_actions={runtimeDiagnostics.action_counts.constraint_action_count} | failure_events={runtimeDiagnostics.action_counts.failure_event_count}
              </p>
            </div>
          ) : null}
          {actionRegimeDetails ? (
            <div className="xl:col-span-2 rounded-lg border border-dashed p-3 text-xs text-muted-foreground">
              <p className="font-medium text-foreground">Typed action/regime details</p>
              <p className="mt-1">{actionRegimeDetails.summary || "No typed action/regime details available."}</p>
              <p className="mt-1">
                risk_actions={actionRegimeDetails.risk_actions.length} | constraint_actions={actionRegimeDetails.constraint_actions.length} | failure_events={actionRegimeDetails.failure_condition_events.length} | regime_periods={actionRegimeDetails.regime_periods.length}
              </p>
            </div>
          ) : null}
          <Table>
            <THead>
              <tr>
                <Th>Regime</Th>
                <Th>Start</Th>
                <Th>End</Th>
                <Th>Trigger</Th>
              </tr>
            </THead>
            <TBody>
              {regimePeriods.length === 0 ? (
                <Tr>
                  <Td>-</Td>
                  <Td>-</Td>
                  <Td>-</Td>
                  <Td>No regime trigger</Td>
                </Tr>
              ) : (
                regimePeriods.map((row, idx) => (
                  <Tr key={`${String(row.regime)}-${idx}`}>
                    <Td>{String(row.regime ?? "-")}</Td>
                    <Td>{row.start ? new Date(String(row.start)).toLocaleString() : "-"}</Td>
                    <Td>{row.end ? new Date(String(row.end)).toLocaleString() : "-"}</Td>
                    <Td>{String(row.trigger ?? "-")}</Td>
                  </Tr>
                ))
              )}
            </TBody>
          </Table>
          <Table>
            <THead>
              <tr>
                <Th>Time</Th>
                <Th>Action</Th>
                <Th>Detail</Th>
              </tr>
            </THead>
            <TBody>
              {riskActions.length === 0 ? (
                <Tr>
                  <Td>-</Td>
                  <Td>-</Td>
                  <Td>No risk actions</Td>
                </Tr>
              ) : (
                riskActions.slice(-60).reverse().map((row, idx) => (
                  <Tr key={`${String(row.action)}-${idx}`}>
                    <Td>{row.time ? new Date(String(row.time)).toLocaleString() : "-"}</Td>
                    <Td>{String(row.action ?? "-")}</Td>
                    <Td>{String(row.detail ?? "-")}</Td>
                  </Tr>
                ))
              )}
            </TBody>
          </Table>
          <Table>
            <THead>
              <tr>
                <Th>Constraint Time</Th>
                <Th>Action</Th>
                <Th>Context</Th>
              </tr>
            </THead>
            <TBody>
              {constraintActions.length === 0 ? (
                <Tr>
                  <Td>-</Td>
                  <Td>-</Td>
                  <Td>No constraint actions</Td>
                </Tr>
              ) : (
                constraintActions.slice(-40).reverse().map((row, idx) => (
                  <Tr key={`${String(row.action)}-${idx}`}>
                    <Td>{row.time ? new Date(String(row.time)).toLocaleString() : "-"}</Td>
                    <Td>{String(row.action ?? "-")}</Td>
                    <Td>{String(row.detail ?? row.instrument ?? row.sector ?? row.symbol ?? "-")}</Td>
                  </Tr>
                ))
              )}
            </TBody>
          </Table>
          <Table>
            <THead>
              <tr>
                <Th>Failure Time</Th>
                <Th>Code</Th>
                <Th>Level</Th>
              </tr>
            </THead>
            <TBody>
              {failureConditionEvents.length === 0 ? (
                <Tr>
                  <Td>-</Td>
                  <Td>-</Td>
                  <Td>No failure-condition events</Td>
                </Tr>
              ) : (
                failureConditionEvents.slice(-40).reverse().map((row, idx) => (
                  <Tr key={`${String(row.code)}-${idx}`}>
                    <Td>{row.time ? new Date(String(row.time)).toLocaleString() : "-"}</Td>
                    <Td>{String(row.code ?? "-")}</Td>
                    <Td>{String(row.level ?? "-")}</Td>
                  </Tr>
                ))
              )}
            </TBody>
          </Table>
        </div>
      </Card>

      <Card>
        <CardHeader>
          <div>
            <CardTitle>Control And Optimizer Details</CardTitle>
            <CardDescription>Typed control, optimizer, budget, and circuit-breaker detail for this strategy run.</CardDescription>
          </div>
        </CardHeader>
        <div className="grid gap-4 xl:grid-cols-2">
          {(controlOptimizerDetails || rejectedOrders.length > 0 || optimizerDiagnostics.length > 0 || circuitBreakerIntervals.length > 0 || riskContributionPoints.length > 0) ? (
            <div className="xl:col-span-2 rounded-lg border border-dashed p-3 text-xs text-muted-foreground">
              <p className="font-medium text-foreground">
                {controlOptimizerDetails ? "Typed control/optimizer details" : "Compatibility control/optimizer details"}
              </p>
              <p className="mt-1">{controlOptimizerDetails?.summary || "Using control/optimizer detail rows from current report payload."}</p>
              <p className="mt-1">
                rejected_orders={rejectedOrders.length} | optimizer_steps={optimizerDiagnostics.length} | circuit_breaker_intervals={circuitBreakerIntervals.length} | risk_points={riskContributionPoints.length}
              </p>
              <p className="mt-1">
                budget_obs={budgetDetail.observations ?? 0} | mean_l1={budgetDetail.mean_l1 ?? "n/a"} | max_l1={budgetDetail.max_l1 ?? "n/a"} | latest_deviation={budgetDetail.latest_deviation_l1 ?? "n/a"}
              </p>
              {controlActionDeepDetails ? (
                <>
                  <p className="mt-1 font-medium text-foreground">Typed deep control/action details</p>
                  <p className="mt-1">{controlActionDeepDetails.summary || "Using typed deep detail rows from current report payload."}</p>
                  <p className="mt-1">
                    cb_rule={circuitBreakerState.rule_type ?? "n/a"} | threshold={circuitBreakerState.threshold ?? "n/a"} | supported={String(
                      circuitBreakerState.rule_type === "drawdown"
                        ? circuitBreakerState.execution_support.drawdown
                        : circuitBreakerState.rule_type === "consecutive_losses"
                          ? circuitBreakerState.execution_support.consecutive_losses
                          : circuitBreakerState.rule_type === "vol_spike"
                            ? circuitBreakerState.execution_support.vol_spike
                            : null
                    )} | deep_optimizer_steps={deepOptimizerSteps.length}
                  </p>
                </>
              ) : null}
            </div>
          ) : null}
          <Table>
            <THead>
              <tr>
                <Th>Rejected Time</Th>
                <Th>Instrument</Th>
                <Th>Reason</Th>
              </tr>
            </THead>
            <TBody>
              {rejectedOrders.length === 0 ? (
                <Tr>
                  <Td>-</Td>
                  <Td>-</Td>
                  <Td>No rejected orders</Td>
                </Tr>
              ) : (
                rejectedOrders.slice(-25).reverse().map((row, idx) => (
                  <Tr key={`reject-${idx}`}>
                    <Td>{row.time ? new Date(String(row.time)).toLocaleString() : "-"}</Td>
                    <Td>{String(row.instrument ?? "-")}</Td>
                    <Td>{String(row.reason ?? row.reason_code ?? row.reason_msg ?? "-")}</Td>
                  </Tr>
                ))
              )}
            </TBody>
          </Table>
          <Table>
            <THead>
              <tr>
                <Th>Optimizer Time</Th>
                <Th>Optimizer</Th>
                <Th>Summary</Th>
              </tr>
            </THead>
            <TBody>
              {optimizerDiagnostics.length === 0 ? (
                <Tr>
                  <Td>-</Td>
                  <Td>-</Td>
                  <Td>No optimizer diagnostics</Td>
                </Tr>
              ) : (
                optimizerDiagnostics.slice(-25).reverse().map((row, idx) => (
                  <Tr key={`optimizer-${idx}`}>
                    <Td>{row.time ? new Date(String(row.time)).toLocaleString() : "-"}</Td>
                    <Td>{String(row.optimizer ?? "-")}</Td>
                    <Td>
                      {`symbol=${String(row.symbol ?? "-")} | w=${String(row.optimized_weight ?? "-")} | gross=${String(row.gross_target ?? "-")} | dev=${String(row.budget_deviation_l1 ?? "-")}`}
                    </Td>
                  </Tr>
                ))
              )}
            </TBody>
          </Table>
          <Table>
            <THead>
              <tr>
                <Th>CB Start</Th>
                <Th>End</Th>
                <Th>Reason</Th>
              </tr>
            </THead>
            <TBody>
              {circuitBreakerIntervals.length === 0 ? (
                <Tr>
                  <Td>-</Td>
                  <Td>-</Td>
                  <Td>No circuit-breaker intervals</Td>
                </Tr>
              ) : (
                circuitBreakerIntervals.slice(-20).reverse().map((row, idx) => (
                  <Tr key={`cb-${idx}`}>
                    <Td>{row.start ? new Date(String(row.start)).toLocaleString() : "-"}</Td>
                    <Td>{row.end ? new Date(String(row.end)).toLocaleString() : "-"}</Td>
                    <Td>{String(row.reason ?? "-")}</Td>
                  </Tr>
                ))
              )}
            </TBody>
          </Table>
          <Table>
            <THead>
              <tr>
                <Th>Risk Time</Th>
                <Th>Deviation</Th>
                <Th>Budget Snapshot</Th>
              </tr>
            </THead>
            <TBody>
              {riskContributionPoints.length === 0 ? (
                <Tr>
                  <Td>-</Td>
                  <Td>-</Td>
                  <Td>No risk-contribution snapshots</Td>
                </Tr>
              ) : (
                riskContributionPoints.slice(-12).reverse().map((row, idx) => (
                  <Tr key={`risk-point-${idx}`}>
                    <Td>{row.time ? new Date(String(row.time)).toLocaleString() : "-"}</Td>
                    <Td>{String(row.deviation_l1 ?? "-")}</Td>
                    <Td>{`target=${formatCompileValue(row.target_budget ?? {})} / achieved=${formatCompileValue(row.achieved_budget ?? {})}`}</Td>
                  </Tr>
                ))
              )}
            </TBody>
          </Table>
          {controlActionDeepDetails ? (
            <Table>
              <THead>
                <tr>
                  <Th>Optimizer Time</Th>
                  <Th>Method</Th>
                  <Th>Assets</Th>
                  <Th>Internals</Th>
                </tr>
              </THead>
              <TBody>
                {deepOptimizerSteps.length === 0 ? (
                  <Tr>
                    <Td>-</Td>
                    <Td>-</Td>
                    <Td>-</Td>
                    <Td>No typed deep optimizer detail</Td>
                  </Tr>
                ) : (
                  deepOptimizerSteps.slice(-12).reverse().map((row, idx) => (
                    <Tr key={`optimizer-deep-${idx}`}>
                      <Td>{row.time ? new Date(String(row.time)).toLocaleString() : "-"}</Td>
                      <Td>{String(row.method ?? row.optimizer ?? "-")}</Td>
                      <Td>{row.assets.length > 0 ? row.assets.join(", ") : String(row.asset_count)}</Td>
                      <Td>
                        {`loss=${String(row.loss_final ?? "-")} | dev=${String(row.budget_deviation_l1 ?? "-")} | target=${summarizeNumericMap(row.target_budget)} | achieved=${summarizeNumericMap(row.achieved_budget)}`}
                      </Td>
                    </Tr>
                  ))
                )}
              </TBody>
            </Table>
          ) : null}
          {controlActionDeepDetails ? (
            <div className="space-y-3 rounded-lg border p-3 text-xs text-muted-foreground xl:col-span-2">
              <p className="font-medium text-foreground">Deep Budget And Risk Breakdown</p>
              <p>
                latest_budget_time={budgetBreakdown.latest_time ? new Date(String(budgetBreakdown.latest_time)).toLocaleString() : "n/a"} | latest_l1={budgetBreakdown.latest_deviation_l1 ?? "n/a"} | peak_time={budgetBreakdown.peak_time ? new Date(String(budgetBreakdown.peak_time)).toLocaleString() : "n/a"} | peak_l1={budgetBreakdown.peak_deviation_l1 ?? "n/a"}
              </p>
              <p>latest_gap={summarizeNumericMap(budgetBreakdown.latest_gap_by_asset)}</p>
              <p>peak_gap={summarizeNumericMap(budgetBreakdown.peak_gap_by_asset)}</p>
              <p>
                latest_risk={riskContributionBreakdown.latest ? `l1=${String(riskContributionBreakdown.latest.deviation_l1 ?? "-")} | gap=${summarizeNumericMap(riskContributionBreakdown.latest.gap_by_asset)}` : "n/a"}
              </p>
              <p>
                peak_risk={riskContributionBreakdown.peak ? `l1=${String(riskContributionBreakdown.peak.deviation_l1 ?? "-")} | gap=${summarizeNumericMap(riskContributionBreakdown.peak.gap_by_asset)}` : "n/a"}
              </p>
            </div>
          ) : null}
        </div>
      </Card>

      <div className="grid gap-4 xl:grid-cols-2">
        <Card>
          <CardHeader>
            <div>
              <CardTitle>Equity Curve</CardTitle>
              <CardDescription>Cumulative equity over the test period.</CardDescription>
            </div>
          </CardHeader>
          {equityCurve.length === 0 ? (
            <EmptyState title="No equity series" description="Series is not available in this report." />
          ) : (
            <div className="h-72">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={equityCurve}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="x" />
                  <YAxis />
                  <Tooltip />
                  <Line type="monotone" dataKey="equity" stroke="hsl(var(--primary))" dot={false} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          )}
        </Card>

        <Card>
          <CardHeader>
            <div>
              <CardTitle>Drawdown Curve</CardTitle>
              <CardDescription>Peak-to-trough drawdown tracking.</CardDescription>
            </div>
          </CardHeader>
          {equityCurve.length === 0 ? (
            <EmptyState title="No drawdown series" description="Series is not available in this report." />
          ) : (
            <div className="h-72">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={equityCurve}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="x" />
                  <YAxis />
                  <Tooltip />
                  <Line type="monotone" dataKey="drawdown" stroke="hsl(var(--destructive))" dot={false} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          )}
        </Card>
      </div>

      <Card>
        <CardHeader>
          <div>
            <CardTitle>Monthly Heatmap</CardTitle>
            <CardDescription>Month-level return distribution.</CardDescription>
          </div>
        </CardHeader>
        {monthlyRows.length === 0 ? (
          <EmptyState title="No monthly data" description="Monthly return bins are not available." />
        ) : (
          <div className="grid grid-cols-2 gap-2 md:grid-cols-6">
            {monthlyRows.map(([month, ret]) => (
              <div key={month} className={`rounded-lg border border-border p-3 ${cellClass(ret)}`}>
                <p className="text-xs text-muted-foreground">{month}</p>
                <p className="text-sm font-semibold">{toPct(ret)}</p>
              </div>
            ))}
          </div>
        )}
      </Card>

      <Card>
        <CardHeader>
          <div>
            <CardTitle>Evidence References</CardTitle>
            <CardDescription>Click reference links for source context.</CardDescription>
          </div>
        </CardHeader>
        {report.evidence_refs.length === 0 ? (
          <div className="rounded-lg border border-border p-3 text-xs text-muted-foreground">
            No explicit references in this run. Pipeline evidence pack remains available via chat/pipeline.
          </div>
        ) : (
          <ul className="space-y-2">
            {report.evidence_refs.map((ref) => (
              <li key={ref}>
                {(() => {
                  const parsed = parseEvidenceRef(ref, evidencePackId);
                  if (parsed.external) {
                    return (
                      <a href={parsed.href} target="_blank" rel="noreferrer" className="text-sm text-primary underline">
                        {parsed.label}
                      </a>
                    );
                  }
                  return (
                    <Link href={parsed.href} className="text-sm text-primary underline">
                      {parsed.label}
                    </Link>
                  );
                })()}
              </li>
            ))}
          </ul>
        )}
      </Card>

      <Card>
        <CardHeader>
          <div>
            <CardTitle>Orders</CardTitle>
            <CardDescription>Submitted and filled orders with reasons.</CardDescription>
          </div>
        </CardHeader>
        {report.orders.length === 0 ? (
          <EmptyState title="No orders" description="No executable orders were generated in this run." />
        ) : (
          <Table>
            <THead>
              <tr>
                <Th>Time</Th>
                <Th>Side</Th>
                <Th>Qty</Th>
                <Th>Status</Th>
                <Th>Reason Code</Th>
                <Th>Reason</Th>
              </tr>
            </THead>
            <TBody>
              {report.orders.slice(-20).reverse().map((row) => (
                <Tr key={row.order_id}>
                  <Td>{new Date(row.time).toLocaleString()}</Td>
                  <Td>{row.side}</Td>
                  <Td>{row.qty}</Td>
                  <Td>{row.status}</Td>
                  <Td>{row.reason_code ?? "-"}</Td>
                  <Td>{row.user_friendly_msg ?? row.reason_msg ?? row.reason}</Td>
                </Tr>
              ))}
            </TBody>
          </Table>
        )}
      </Card>

      <Card>
        <CardHeader>
          <div>
            <CardTitle>Trades</CardTitle>
            <CardDescription>Real fills used for PnL and chart generation. Supports filter/sort.</CardDescription>
          </div>
        </CardHeader>
        <div className="mb-2 grid gap-2 md:grid-cols-3">
          <select
            value={tradeSideFilter}
            onChange={(e) => setTradeSideFilter((e.target.value as "all" | "buy" | "sell") || "all")}
            className="h-9 rounded-md border border-input bg-background px-3 text-sm"
          >
            <option value="all">All sides</option>
            <option value="buy">Buy</option>
            <option value="sell">Sell</option>
          </select>
          <input
            value={tradeInstrumentFilter}
            onChange={(e) => setTradeInstrumentFilter(e.target.value)}
            className="h-9 rounded-md border border-input bg-background px-3 text-sm"
            placeholder="Filter instrument"
          />
          <select
            value={tradeSort}
            onChange={(e) =>
              setTradeSort(
                (e.target.value as "time_desc" | "time_asc" | "commission_desc" | "slippage_desc" | "qty_desc") ||
                  "time_desc"
              )
            }
            className="h-9 rounded-md border border-input bg-background px-3 text-sm"
          >
            <option value="time_desc">Time desc</option>
            <option value="time_asc">Time asc</option>
            <option value="commission_desc">Commission desc</option>
            <option value="slippage_desc">Slippage desc</option>
            <option value="qty_desc">Qty desc</option>
          </select>
        </div>
        {report.trades.length === 0 ? (
          <EmptyState title="No trades" description="No fills were executed in this run." />
        ) : (
          <Table>
            <THead>
              <tr>
                <Th>Time</Th>
                <Th>Side</Th>
                <Th>Price</Th>
                <Th>Qty</Th>
                <Th>Commission</Th>
                <Th>Slippage</Th>
              </tr>
            </THead>
            <TBody>
              {tradesView.map((row) => (
                <Tr key={row.trade_id}>
                  <Td>{new Date(row.time).toLocaleString()}</Td>
                  <Td>{row.side}</Td>
                  <Td>{row.price}</Td>
                  <Td>{row.qty}</Td>
                  <Td>{row.commission}</Td>
                  <Td>{row.slippage}</Td>
                </Tr>
              ))}
            </TBody>
          </Table>
        )}
      </Card>

      <Card>
        <CardHeader>
          <div>
            <CardTitle>Positions</CardTitle>
            <CardDescription>Portfolio timeline from mark-to-market snapshots.</CardDescription>
          </div>
        </CardHeader>
        {report.positions.length === 0 ? (
          <EmptyState title="No positions" description="No position snapshots are available." />
        ) : (
          <Table>
            <THead>
              <tr>
                <Th>Time</Th>
                <Th>Qty</Th>
                <Th>Avg Px</Th>
                <Th>Market Px</Th>
                <Th>Market Value</Th>
                <Th>Cash</Th>
                <Th>Equity</Th>
              </tr>
            </THead>
            <TBody>
              {report.positions.slice(-20).reverse().map((row) => (
                <Tr key={`${row.time}-${row.instrument}`}>
                  <Td>{new Date(row.time).toLocaleString()}</Td>
                  <Td>{row.qty}</Td>
                  <Td>{row.avg_price}</Td>
                  <Td>{row.market_price}</Td>
                  <Td>{row.market_value}</Td>
                  <Td>{row.cash}</Td>
                  <Td>{row.equity}</Td>
                </Tr>
              ))}
            </TBody>
          </Table>
        )}
      </Card>
    </div>
  );
}
