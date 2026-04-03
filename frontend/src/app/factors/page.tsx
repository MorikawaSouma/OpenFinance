"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { EmptyState } from "@/components/common/empty-state";
import { useCatalogSummaryState } from "@/components/providers/catalog-summary-provider";
import { useResearchContextState } from "@/components/providers/research-context-provider";
import { useTaskRealtimeState } from "@/components/providers/task-realtime-provider";
import { useWorkbenchShellActions } from "@/components/providers/workbench-shell-provider";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { api } from "@/lib/api";
import type { FactorDetail, FactorMultiMarketCompareResponse, FactorSummary } from "@/lib/types";

const MARKET_OPTIONS = ["US", "CN", "JP", "CRYPTO"] as const;

export default function FactorsPage() {
  const { datasets } = useCatalogSummaryState();
  const { lastSessionId } = useResearchContextState();
  const { tasks } = useTaskRealtimeState();
  const { pushToast } = useWorkbenchShellActions();
  const [loading, setLoading] = useState(true);
  const [rows, setRows] = useState<FactorSummary[]>([]);
  const [activeVersion, setActiveVersion] = useState<string | null>(null);
  const [detail, setDetail] = useState<FactorDetail | null>(null);
  const [running, setRunning] = useState(false);
  const [factorTaskId, setFactorTaskId] = useState("");

  const [factorId, setFactorId] = useState("intraday_formula");
  const [formula, setFormula] = useState("Rank(Ts_Mean(close, 20))");
  const [inputs, setInputs] = useState("close,open");
  const [availabilityLag, setAvailabilityLag] = useState("0s");
  const [failureConditions, setFailureConditions] = useState("high_volatility,range_bound_market,liquidity_dry_up");
  const [costSensitivityLevel, setCostSensitivityLevel] = useState("medium");
  const [costSensitivityRationale, setCostSensitivityRationale] = useState("Moderate turnover expected during periodic rebalancing.");
  const [expectedHorizon, setExpectedHorizon] = useState("swing");
  const [datasetVersion, setDatasetVersion] = useState("");
  const [multiMarketRunning, setMultiMarketRunning] = useState(false);
  const [multiMarketResult, setMultiMarketResult] = useState<FactorMultiMarketCompareResponse | null>(null);
  const [multiMarketTaskId, setMultiMarketTaskId] = useState("");
  const [multiMarketStart, setMultiMarketStart] = useState("2023-01-01");
  const [multiMarketEnd, setMultiMarketEnd] = useState("2024-12-31");
  const [multiMarketUniverse, setMultiMarketUniverse] = useState("AAA,BBB,CCC,DDD");
  const [multiMarketMarkets, setMultiMarketMarkets] = useState<string[]>(["US", "JP"]);
  const factorTaskEventRef = useRef("");
  const multiMarketTaskEventRef = useRef("");

  const latestDatasetVersion = datasets[0]?.dataset_version ?? null;
  const sessionTaskScope = useMemo(() => (lastSessionId || "factors").trim(), [lastSessionId]);

  const factorTask = useMemo(() => {
    const byId = tasks.find((row) => String(row.task_id) === factorTaskId);
    if (byId) return byId;
    return tasks.find((row) => {
      if (String(row.task_type) !== "factor.run") return false;
      const metaSession = String((row.meta ?? {}).session_id ?? "").trim();
      return metaSession === sessionTaskScope;
    }) ?? null;
  }, [factorTaskId, sessionTaskScope, tasks]);

  const factorTaskRunning = useMemo(() => {
    if (!factorTask) return false;
    const status = String(factorTask.status || "").toLowerCase();
    return !["done", "error", "failed", "canceled"].includes(status);
  }, [factorTask]);

  const activeMultiMarketTask = useMemo(() => {
    const byId = tasks.find((row) => String(row.task_id) === multiMarketTaskId);
    if (byId) return byId;
    return tasks.find((row) => {
      if (String(row.task_type) !== "factor.multi_market_compare") return false;
      const metaSession = String((row.meta ?? {}).session_id ?? "").trim();
      return metaSession === sessionTaskScope;
    }) ?? null;
  }, [multiMarketTaskId, sessionTaskScope, tasks]);

  const activeMultiMarketTaskRunning = useMemo(() => {
    if (!activeMultiMarketTask) return false;
    const status = String(activeMultiMarketTask.status || "").toLowerCase();
    return !["done", "error", "failed", "canceled"].includes(status);
  }, [activeMultiMarketTask]);

  const loadDetail = useCallback(async (version: string) => {
    setActiveVersion(version);
    try {
      const payload = await api.getFactor(version);
      setDetail(payload);
    } catch (err) {
      setDetail(null);
      pushToast("Load factor detail failed", err instanceof Error ? err.message : "Unknown error", "error");
    }
  }, [pushToast]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const payload = await api.getFactors();
      setRows(payload);
      if (payload.length > 0) {
        const next = activeVersion && payload.some((item) => item.version === activeVersion) ? activeVersion : payload[0].version;
        await loadDetail(next);
      } else {
        setActiveVersion(null);
        setDetail(null);
      }
    } finally {
      setLoading(false);
    }
  }, [activeVersion, loadDetail]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (!factorTask) return;
    const status = String(factorTask.status || "").toLowerCase();
    const eventKey = `${factorTask.task_id}:${status}`;
    if (factorTaskEventRef.current === eventKey) return;
    factorTaskEventRef.current = eventKey;

    if (status === "done") {
      const result = factorTask.result && typeof factorTask.result === "object" ? (factorTask.result as Record<string, unknown>) : {};
      const factorVersion = String(result.factor_version ?? "").trim();
      const taskShort = String(factorTask.task_id).slice(0, 8);
      pushToast("Factor computed", `Task ${taskShort} completed.`, "success");
      void (async () => {
        await load();
        if (factorVersion) {
          await loadDetail(factorVersion);
        }
      })();
      return;
    }
    if (status === "error" || status === "failed" || status === "canceled") {
      pushToast("Run factor failed", String(factorTask.error || factorTask.message || "Task failed"), "error");
    }
  }, [factorTask, load, loadDetail, pushToast]);

  useEffect(() => {
    if (!activeMultiMarketTask) return;
    const status = String(activeMultiMarketTask.status || "").toLowerCase();
    const eventKey = `${activeMultiMarketTask.task_id}:${status}`;
    if (multiMarketTaskEventRef.current === eventKey) return;
    multiMarketTaskEventRef.current = eventKey;

    if (status === "done") {
      const result =
        activeMultiMarketTask.result && typeof activeMultiMarketTask.result === "object"
          ? (activeMultiMarketTask.result as Record<string, unknown>)
          : {};
      const payload: FactorMultiMarketCompareResponse = {
        compare_id: String(result.compare_id ?? ""),
        requested_metrics: Array.isArray(result.requested_metrics)
          ? result.requested_metrics.map((item) => String(item))
          : [],
        per_market_metrics: Array.isArray(result.per_market_metrics)
          ? (result.per_market_metrics as FactorMultiMarketCompareResponse["per_market_metrics"])
          : [],
        per_market_decay_curves: Array.isArray(result.per_market_decay_curves)
          ? (result.per_market_decay_curves as FactorMultiMarketCompareResponse["per_market_decay_curves"])
          : [],
        summary_insights: Array.isArray(result.summary_insights)
          ? result.summary_insights.map((item) => String(item))
          : [],
        parent_task_id: String(activeMultiMarketTask.task_id),
        child_task_ids: Array.isArray(result.child_task_ids)
          ? result.child_task_ids.map((item) => String(item))
          : [],
      };
      setMultiMarketResult(payload);
      const taskShort = String(activeMultiMarketTask.task_id).slice(0, 8);
      pushToast("Factor multi-market compare ready", `Task ${taskShort} completed.`, "success");
      return;
    }
    if (status === "error" || status === "failed" || status === "canceled") {
      pushToast("Run compare failed", String(activeMultiMarketTask.error || activeMultiMarketTask.message || "Task failed"), "error");
    }
  }, [activeMultiMarketTask, pushToast]);

  async function onRunFormula() {
    setRunning(true);
    try {
      const task = await api.submitFactorRun({
        dataset_version: datasetVersion || latestDatasetVersion || undefined,
        factor_id: factorId,
        formula,
        availability_lag: availabilityLag,
        failure_conditions: failureConditions
          .split(",")
          .map((item) => item.trim())
          .filter(Boolean),
        cost_sensitivity_level: costSensitivityLevel.trim().toLowerCase(),
        cost_sensitivity_rationale: costSensitivityRationale.trim(),
        expected_horizon: expectedHorizon.trim() || undefined,
        inputs: inputs
          .split(",")
          .map((item) => item.trim())
          .filter(Boolean),
        session_id: sessionTaskScope,
      });
      setFactorTaskId(String(task.task_id));
      pushToast("Task submitted", `Factor task ${String(task.task_id).slice(0, 8)} is running.`, "success");
    } catch (err) {
      pushToast("Run factor failed", err instanceof Error ? err.message : "Unknown error", "error");
    } finally {
      setRunning(false);
    }
  }

  function toggleMultiMarket(market: string) {
    setMultiMarketMarkets((prev) => {
      if (prev.includes(market)) {
        return prev.filter((item) => item !== market);
      }
      return [...prev, market];
    });
  }

  async function onRunMultiMarket() {
    if (!detail) {
      pushToast("Run compare failed", "Select a factor version first.", "error");
      return;
    }
    if (multiMarketMarkets.length < 2) {
      pushToast("Run compare failed", "Please select at least two markets.", "error");
      return;
    }
    setMultiMarketRunning(true);
    try {
      const task = await api.submitFactorMultiMarketCompare({
        factor_id: detail.factor_id,
        factor_versions: [detail.version],
        markets: multiMarketMarkets,
        universe: multiMarketUniverse
          .split(",")
          .map((item) => item.trim())
          .filter(Boolean),
        start: multiMarketStart,
        end: multiMarketEnd,
        seed: 42,
        eval_metrics: ["IC", "RankIC", "decay", "coverage"],
        session_id: sessionTaskScope,
      });
      setMultiMarketTaskId(String(task.task_id));
      setMultiMarketResult(null);
      pushToast("Task submitted", `Compare task ${String(task.task_id).slice(0, 8)} is running.`, "success");
    } catch (err) {
      pushToast("Run compare failed", err instanceof Error ? err.message : "Unknown error", "error");
    } finally {
      setMultiMarketRunning(false);
    }
  }

  const reportRows = useMemo(() => {
    const report = detail?.report as Record<string, unknown> | null | undefined;
    if (!report || typeof report !== "object") return [];
    return [
      ["IC mean", report.ic_mean],
      ["RankIC mean", report.rank_ic_mean],
      ["t-stat", report.t_stat],
      ["coverage", report.coverage],
      ["missing_rate", report.missing_rate],
    ];
  }, [detail]);

  const healthRows = useMemo(() => {
    const report = detail?.report as Record<string, unknown> | null | undefined;
    if (!report || typeof report !== "object") return { summary: [], sensitivity: [], oosDecay: [] };
    const health = report.health_report as Record<string, unknown> | undefined;
    if (!health || typeof health !== "object") return { summary: [], sensitivity: [], oosDecay: [] };
    const summary = [
      ["stability_score", health.stability_score],
      ["oos_gap", health.oos_gap],
      ["sensitivity_grid_size", health.sensitivity_grid_size],
      ["in_sample_ic_mean", health.in_sample_ic_mean],
      ["out_sample_ic_mean", health.out_sample_ic_mean],
    ];
    const sensitivity = Array.isArray(health.sensitivity) ? (health.sensitivity as Array<Record<string, unknown>>) : [];
    const oosDecay = Array.isArray(health.oos_decay_gap_curve)
      ? (health.oos_decay_gap_curve as Array<Record<string, unknown>>)
      : [];
    return { summary, sensitivity, oosDecay };
  }, [detail]);

  const portrait = useMemo(() => {
    const spec = detail?.spec as Record<string, unknown> | undefined;
    if (!spec) return { failureConditions: [], costLevel: "-", costRationale: "-", expectedHorizon: "-" };
    const failure = Array.isArray(spec.failure_conditions)
      ? spec.failure_conditions
          .map((item) => {
            if (typeof item === "string") return item;
            if (item && typeof item === "object" && "code" in item) {
              const code = (item as Record<string, unknown>).code;
              return typeof code === "string" ? code : "";
            }
            return "";
          })
          .filter(Boolean)
      : [];
    const cost = (spec.cost_sensitivity as Record<string, unknown> | undefined) ?? {};
    const costLevel = typeof cost.level === "string" ? cost.level : "-";
    const costRationale = typeof cost.rationale === "string" ? cost.rationale : "-";
    const expected = typeof spec.expected_horizon === "string" ? spec.expected_horizon : "-";
    return { failureConditions: failure, costLevel, costRationale, expectedHorizon: expected };
  }, [detail]);

  const multiMarketMetricsRows = useMemo(() => {
    if (!multiMarketResult) return [];
    return multiMarketResult.per_market_metrics;
  }, [multiMarketResult]);

  const multiMarketChartData = useMemo(() => {
    if (!multiMarketResult) return [];
    const byLag = new Map<number, Record<string, number | string>>();
    for (const curve of multiMarketResult.per_market_decay_curves) {
      const key = `${curve.market}`;
      for (const point of curve.points) {
        if (!byLag.has(point.lag)) {
          byLag.set(point.lag, { lag: point.lag });
        }
        byLag.get(point.lag)![key] = point.ic;
      }
    }
    return Array.from(byLag.values()).sort((a, b) => Number(a.lag) - Number(b.lag));
  }, [multiMarketResult]);

  const multiMarketLineKeys = useMemo(() => {
    if (!multiMarketResult) return [];
    return Array.from(new Set(multiMarketResult.per_market_decay_curves.map((curve) => curve.market)));
  }, [multiMarketResult]);

  return (
    <div className="grid gap-4 xl:grid-cols-12">
      <Card className="xl:col-span-4">
        <CardHeader>
          <CardTitle>Factor Library</CardTitle>
          <CardDescription>Reusable factor assets and versions.</CardDescription>
        </CardHeader>
        <CardContent>
          {loading ? (
            <div className="space-y-2">
              {Array.from({ length: 6 }).map((_, i) => (
                <Skeleton key={i} className="h-14 w-full" />
              ))}
            </div>
          ) : rows.length === 0 ? (
            <EmptyState title="No factors yet" description="Run a formula factor to create the first version." />
          ) : (
            <div className="space-y-2">
              {rows.map((row) => (
                <button
                  key={row.version}
                  onClick={() => void loadDetail(row.version)}
                  className={`w-full rounded-lg border p-2 text-left text-xs ${
                    activeVersion === row.version ? "border-primary bg-primary/10" : "hover:bg-accent/60"
                  }`}
                >
                  <p className="font-medium">{row.factor_id}</p>
                  <p className="mt-1 text-muted-foreground">{row.version}</p>
                  <div className="mt-1 flex gap-1">
                    <Badge variant="muted">{row.availability_lag}</Badge>
                    <Badge variant={row.has_report ? "success" : "muted"}>
                      {row.has_report ? "report" : "no-report"}
                    </Badge>
                  </div>
                </button>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      <div className="grid gap-4 xl:col-span-8">
        <Card>
          <CardHeader>
            <CardTitle>Create Formula Factor</CardTitle>
            <CardDescription>Safe subset: + - * /, Ts_Mean, Ts_Std, Shift, Rank, ZScore, Clip, Winsorize.</CardDescription>
          </CardHeader>
          <CardContent className="grid gap-2 md:grid-cols-2">
            <Input value={factorId} onChange={(e) => setFactorId(e.target.value)} placeholder="factor_id" />
            <Input value={availabilityLag} onChange={(e) => setAvailabilityLag(e.target.value)} placeholder="availability lag e.g. 0s/1d" />
            <Input
              value={costSensitivityLevel}
              onChange={(e) => setCostSensitivityLevel(e.target.value)}
              placeholder="cost sensitivity level: low|medium|high"
            />
            <Input
              value={expectedHorizon}
              onChange={(e) => setExpectedHorizon(e.target.value)}
              placeholder="expected horizon (optional): intraday|swing|long_only"
            />
            <Input value={inputs} onChange={(e) => setInputs(e.target.value)} placeholder="inputs e.g. close,open,volume" className="md:col-span-2" />
            <Textarea
              value={costSensitivityRationale}
              onChange={(e) => setCostSensitivityRationale(e.target.value)}
              placeholder="cost sensitivity rationale"
              className="md:col-span-2"
            />
            <Input
              value={failureConditions}
              onChange={(e) => setFailureConditions(e.target.value)}
              placeholder="failure conditions, comma-separated"
              className="md:col-span-2"
            />
            <Input
              value={formula}
              onChange={(e) => setFormula(e.target.value)}
              placeholder="formula e.g. Rank(Ts_Mean(close, 20))"
              className="md:col-span-2"
            />
            <Input
              value={datasetVersion}
              onChange={(e) => setDatasetVersion(e.target.value)}
              placeholder={`dataset_version (optional, default latest: ${latestDatasetVersion ?? "n/a"})`}
              className="md:col-span-2"
            />
            <Button onClick={onRunFormula} disabled={running || factorTaskRunning} className="md:col-span-2">
              {running ? "Submitting..." : factorTaskRunning ? "Running..." : "Run And Save Factor"}
            </Button>
            {factorTask ? (
              <div className="md:col-span-2 rounded border border-muted/40 bg-muted/10 px-3 py-2 text-xs text-muted-foreground">
                <p>
                  task_id={String(factorTask.task_id)} | status={String(factorTask.status)} | progress=
                  {Math.max(0, Math.min(100, Number(factorTask.progress ?? 0)))}%
                </p>
                <Link href={`/tasks?focus_task_id=${encodeURIComponent(String(factorTask.task_id))}`} className="text-primary underline">
                  Open Tasks
                </Link>
              </div>
            ) : null}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Factor Card</CardTitle>
            <CardDescription>Spec, validation, and market applicability.</CardDescription>
          </CardHeader>
          <CardContent>
            {!detail ? (
              <EmptyState title="Select a factor version" description="Choose a factor from the library list." />
            ) : (
              <div className="space-y-3 text-xs">
                <div className="rounded-lg border p-3">
                  <p>factor_id: <span className="font-semibold">{detail.factor_id}</span></p>
                  <p>version: <span className="font-semibold">{detail.version}</span></p>
                  <p>dataset_schema: {detail.dataset_schema_version}</p>
                  <p>inputs_signature: {detail.inputs_signature}</p>
                  <p>availability_lag: {detail.availability_lag}</p>
                </div>
                <div className="rounded-lg border p-3">
                  <p className="mb-1 font-semibold">Portrait</p>
                  <p>
                    cost_sensitivity: <span className="font-medium">{portrait.costLevel}</span>
                  </p>
                  <p className="text-muted-foreground">{portrait.costRationale}</p>
                  <p>
                    expected_horizon: <span className="font-medium">{portrait.expectedHorizon}</span>
                  </p>
                  <p className="mt-1 font-semibold">failure_conditions</p>
                  {portrait.failureConditions.length === 0 ? (
                    <p className="text-muted-foreground">No failure conditions recorded.</p>
                  ) : (
                    <div className="flex flex-wrap gap-1">
                      {portrait.failureConditions.map((item) => (
                        <Badge key={item} variant="muted">
                          {item}
                        </Badge>
                      ))}
                    </div>
                  )}
                </div>
                <div className="rounded-lg border p-3">
                  <p className="mb-1 font-semibold">Validation Report</p>
                  <Tabs defaultValue="validation">
                    <TabsList>
                      <TabsTrigger value="validation">Validation</TabsTrigger>
                      <TabsTrigger value="health">Health</TabsTrigger>
                      <TabsTrigger value="multi-market">Multi-Market</TabsTrigger>
                    </TabsList>
                    <TabsContent value="validation">
                      {reportRows.length === 0 ? (
                        <p className="text-muted-foreground">No report found yet for this version.</p>
                      ) : (
                        <div className="space-y-1">
                          {reportRows.map(([k, v]) => (
                            <p key={String(k)}>
                              {String(k)}: <span className="font-medium">{String(v ?? "-")}</span>
                            </p>
                          ))}
                          <p>
                            turnover_proxy:{" "}
                            <span className="font-medium">
                              {String((detail.report as Record<string, unknown> | null | undefined)?.turnover_proxy ?? "-")}
                            </span>
                          </p>
                          <p className="pt-1 font-semibold">OOS Split</p>
                          <p className="text-muted-foreground">
                            ratio: {String((detail.report as Record<string, unknown> | null | undefined)?.oos_split_ratio ?? "-")}
                          </p>
                          <p className="text-muted-foreground">
                            in_sample_ic_mean:{" "}
                            {String((detail.report as Record<string, unknown> | null | undefined)?.in_sample_ic_mean ?? "-")}
                          </p>
                          <p className="text-muted-foreground">
                            out_sample_ic_mean:{" "}
                            {String((detail.report as Record<string, unknown> | null | undefined)?.out_sample_ic_mean ?? "-")}
                          </p>
                          <p className="text-muted-foreground">
                            in_sample_rank_ic_mean:{" "}
                            {String((detail.report as Record<string, unknown> | null | undefined)?.in_sample_rank_ic_mean ?? "-")}
                          </p>
                          <p className="text-muted-foreground">
                            out_sample_rank_ic_mean:{" "}
                            {String((detail.report as Record<string, unknown> | null | undefined)?.out_sample_rank_ic_mean ?? "-")}
                          </p>
                        </div>
                      )}
                    </TabsContent>
                    <TabsContent value="health">
                      {healthRows.summary.length === 0 ? (
                        <p className="text-muted-foreground">No health report found yet for this version.</p>
                      ) : (
                        <div className="space-y-2">
                          <div className="space-y-1">
                            {healthRows.summary.map(([k, v]) => (
                              <p key={String(k)}>
                                {String(k)}: <span className="font-medium">{String(v ?? "-")}</span>
                              </p>
                            ))}
                            <p className="text-muted-foreground">
                              health_report_artifact:{" "}
                              {String((detail.report as Record<string, unknown> | null | undefined)?.health_report_artifact_path ?? "-")}
                            </p>
                          </div>
                          <div>
                            <p className="font-semibold">OOS Decay Compare</p>
                            {healthRows.oosDecay.length === 0 ? (
                              <p className="text-muted-foreground">No OOS decay comparison.</p>
                            ) : (
                              <div className="space-y-1">
                                {healthRows.oosDecay.map((row, idx) => (
                                  <p key={`oos-decay-${idx}`} className="text-muted-foreground">
                                    lag {String(row.lag)}: is={String(row.in_sample_ic)} oos={String(row.out_sample_ic)} gap={String(row.gap)}
                                  </p>
                                ))}
                              </div>
                            )}
                          </div>
                          <div>
                            <p className="font-semibold">Parameter Sensitivity</p>
                            {healthRows.sensitivity.length === 0 ? (
                              <p className="text-muted-foreground">No sensitivity rows.</p>
                            ) : (
                              <div className="overflow-x-auto rounded border">
                                <table className="w-full text-left text-[11px]">
                                  <thead className="bg-muted/40">
                                    <tr>
                                      <th className="px-2 py-1">variant</th>
                                      <th className="px-2 py-1">params</th>
                                      <th className="px-2 py-1">ic</th>
                                      <th className="px-2 py-1">ic_delta</th>
                                      <th className="px-2 py-1">rank_ic</th>
                                      <th className="px-2 py-1">rank_ic_delta</th>
                                    </tr>
                                  </thead>
                                  <tbody>
                                    {healthRows.sensitivity.map((row, idx) => (
                                      <tr key={`sensitivity-${idx}`} className="border-t">
                                        <td className="px-2 py-1">{String(row.variant_id ?? "-")}</td>
                                        <td className="px-2 py-1">{JSON.stringify(row.params ?? {})}</td>
                                        <td className="px-2 py-1">{String(row.ic_mean ?? "-")}</td>
                                        <td className="px-2 py-1">{String(row.ic_delta ?? "-")}</td>
                                        <td className="px-2 py-1">{String(row.rank_ic_mean ?? "-")}</td>
                                        <td className="px-2 py-1">{String(row.rank_ic_delta ?? "-")}</td>
                                      </tr>
                                    ))}
                                  </tbody>
                                </table>
                              </div>
                            )}
                          </div>
                        </div>
                      )}
                    </TabsContent>
                    <TabsContent value="multi-market">
                      <div className="space-y-3">
                        <div className="rounded-lg border p-3">
                          <p className="mb-2 font-semibold">Compare Settings</p>
                          <div className="grid gap-2 md:grid-cols-2">
                            <Input
                              value={multiMarketStart}
                              onChange={(e) => setMultiMarketStart(e.target.value)}
                              placeholder="start YYYY-MM-DD"
                            />
                            <Input
                              value={multiMarketEnd}
                              onChange={(e) => setMultiMarketEnd(e.target.value)}
                              placeholder="end YYYY-MM-DD"
                            />
                            <Input
                              value={multiMarketUniverse}
                              onChange={(e) => setMultiMarketUniverse(e.target.value)}
                              placeholder="universe, comma-separated"
                              className="md:col-span-2"
                            />
                          </div>
                          <div className="mt-2 flex flex-wrap gap-1">
                            {MARKET_OPTIONS.map((market) => (
                              <Button
                                key={market}
                                type="button"
                                size="sm"
                                variant={multiMarketMarkets.includes(market) ? "default" : "outline"}
                                onClick={() => toggleMultiMarket(market)}
                              >
                                {market}
                              </Button>
                            ))}
                          </div>
                          <Button
                            onClick={onRunMultiMarket}
                            disabled={multiMarketRunning || activeMultiMarketTaskRunning || multiMarketMarkets.length < 2 || !detail}
                            className="mt-3"
                          >
                            {multiMarketRunning
                              ? "Submitting..."
                              : activeMultiMarketTaskRunning
                                ? "Running..."
                                : "Run Multi-Market Compare"}
                          </Button>
                          {activeMultiMarketTask ? (
                            <div className="mt-2 rounded border border-muted/40 bg-muted/10 px-3 py-2 text-xs text-muted-foreground">
                              <p>
                                task_id={String(activeMultiMarketTask.task_id)} | status={String(activeMultiMarketTask.status)} | progress=
                                {Math.max(0, Math.min(100, Number(activeMultiMarketTask.progress ?? 0)))}%
                              </p>
                              <Link
                                href={`/tasks?focus_task_id=${encodeURIComponent(String(activeMultiMarketTask.task_id))}`}
                                className="text-primary underline"
                              >
                                Open Tasks
                              </Link>
                            </div>
                          ) : null}
                        </div>

                        {!multiMarketResult ? (
                          <p className="text-muted-foreground">Run compare to view IC/RankIC/decay/coverage by market.</p>
                        ) : (
                          <div className="space-y-3">
                            <div className="rounded-lg border p-3">
                              <p>
                                compare_id: <span className="font-medium">{multiMarketResult.compare_id}</span>
                              </p>
                              <p className="text-muted-foreground">
                                metrics: {multiMarketResult.requested_metrics.join(", ")}
                              </p>
                              <div className="mt-2 space-y-1 text-muted-foreground">
                                {multiMarketResult.summary_insights.map((item, idx) => (
                                  <p key={`insight-${idx}`}>- {item}</p>
                                ))}
                              </div>
                            </div>

                            {multiMarketChartData.length === 0 ? null : (
                              <div className="h-72 rounded-lg border p-2">
                                <ResponsiveContainer width="100%" height="100%">
                                  <LineChart data={multiMarketChartData}>
                                    <CartesianGrid strokeDasharray="3 3" />
                                    <XAxis dataKey="lag" />
                                    <YAxis />
                                    <Tooltip />
                                    <Legend />
                                    {multiMarketLineKeys.map((key, idx) => (
                                      <Line
                                        key={key}
                                        type="monotone"
                                        dataKey={key}
                                        dot={false}
                                        stroke={idx % 2 === 0 ? "hsl(var(--primary))" : "hsl(var(--destructive))"}
                                        strokeWidth={2}
                                      />
                                    ))}
                                  </LineChart>
                                </ResponsiveContainer>
                              </div>
                            )}

                            <div className="overflow-x-auto rounded border">
                              <table className="w-full text-left text-[11px]">
                                <thead className="bg-muted/40">
                                  <tr>
                                    <th className="px-2 py-1">market</th>
                                    <th className="px-2 py-1">ic</th>
                                    <th className="px-2 py-1">rank_ic</th>
                                    <th className="px-2 py-1">decay_ratio</th>
                                    <th className="px-2 py-1">half_life_lag</th>
                                    <th className="px-2 py-1">coverage</th>
                                    <th className="px-2 py-1">spread_bps</th>
                                    <th className="px-2 py-1">cost_pressure</th>
                                  </tr>
                                </thead>
                                <tbody>
                                  {multiMarketMetricsRows.map((row, idx) => (
                                    <tr key={`mm-row-${idx}`} className="border-t">
                                      <td className="px-2 py-1">{row.market}</td>
                                      <td className="px-2 py-1">{row.ic_mean.toFixed(4)}</td>
                                      <td className="px-2 py-1">{row.rank_ic_mean.toFixed(4)}</td>
                                      <td className="px-2 py-1">{row.decay_ratio.toFixed(4)}</td>
                                      <td className="px-2 py-1">{row.decay_half_life_lag}</td>
                                      <td className="px-2 py-1">{row.coverage.toFixed(4)}</td>
                                      <td className="px-2 py-1">{row.avg_spread_bps.toFixed(2)}</td>
                                      <td className="px-2 py-1">{row.estimated_cost_pressure.toFixed(5)}</td>
                                    </tr>
                                  ))}
                                </tbody>
                              </table>
                            </div>
                          </div>
                        )}
                      </div>
                    </TabsContent>
                  </Tabs>
                </div>
                <details className="rounded-lg border p-3">
                  <summary className="cursor-pointer font-semibold">Raw Spec</summary>
                  <pre className="mt-2 overflow-x-auto text-[11px] text-muted-foreground">
                    {JSON.stringify(detail.spec, null, 2)}
                  </pre>
                </details>
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
