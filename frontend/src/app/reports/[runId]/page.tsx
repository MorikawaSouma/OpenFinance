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
import { useWorkbench } from "@/components/providers/workbench-provider";
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
  const { mode, pushToast } = useWorkbench();
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
  const regimePeriods = Array.isArray(report?.diagnostics?.regime_periods)
    ? (report?.diagnostics?.regime_periods as Array<Record<string, unknown>>)
    : [];
  const riskActions = Array.isArray(report?.diagnostics?.risk_actions)
    ? (report?.diagnostics?.risk_actions as Array<Record<string, unknown>>)
    : [];
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
  const strategyDecision =
    report?.strategy_decision && typeof report.strategy_decision === "object"
      ? (report.strategy_decision as Record<string, unknown>)
      : null;
  const strategyDecisionSelected =
    strategyDecision && typeof strategyDecision.selected === "object"
      ? (strategyDecision.selected as Record<string, unknown>)
      : null;
  const strategyDecisionCandidates = Array.isArray(strategyDecision?.candidates)
    ? (strategyDecision.candidates as Array<Record<string, unknown>>)
    : [];

  const keyMetrics = useMemo(() => {
    if (!report) return [];
    return [
      ["total_return", report.metrics.total_return],
      ["sharpe", report.metrics.sharpe],
      ["max_drawdown", report.metrics.max_drawdown],
      ["volatility", report.metrics.volatility],
      ["trade_count", report.metrics.trade_count],
      ["risk_scale", report.metrics.risk_scale],
    ];
  }, [report]);

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
    () => Object.entries(report?.attribution?.instrument_pnl_contrib ?? {}),
    [report]
  );
  const sectorAttribution = useMemo(
    () => Object.entries(report?.attribution?.sector_pnl_contrib ?? {}),
    [report]
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

      {strategyDecision ? (
        <Card>
          <CardHeader>
            <div>
              <CardTitle>Strategy Decision</CardTitle>
              <CardDescription>A/B candidates and selected trade-off rationale.</CardDescription>
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
            </div>
            <Table>
              <THead>
                <tr>
                  <Th>Candidate</Th>
                  <Th>Cost Profile</Th>
                  <Th>Why Not Selected</Th>
                </tr>
              </THead>
              <TBody>
                {strategyDecisionCandidates.length === 0 ? (
                  <Tr>
                    <Td>-</Td>
                    <Td>-</Td>
                    <Td>No candidate records</Td>
                  </Tr>
                ) : (
                  strategyDecisionCandidates.slice(0, 4).map((row, idx) => (
                    <Tr key={`decision-candidate-${idx}`}>
                      <Td>{String(row.name ?? "-")}</Td>
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
            <CardDescription>Commission and slippage from actual fills.</CardDescription>
          </div>
        </CardHeader>
        <div className="grid gap-2 text-sm md:grid-cols-3">
          <p>commission_sum: <span className="font-medium">{String(report.cost_breakdown?.commission_sum ?? report.cost_breakdown?.commission ?? 0)}</span></p>
          <p>slippage_sum: <span className="font-medium">{String(report.cost_breakdown?.slippage_sum ?? report.cost_breakdown?.slippage ?? 0)}</span></p>
          <p>total cost: <span className="font-medium">{String(report.cost_breakdown?.total ?? 0)}</span></p>
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
                </tr>
              </THead>
              <TBody>
                {instrumentAttribution.map(([instrument, pnl]) => (
                  <Tr key={instrument}>
                    <Td>{instrument}</Td>
                    <Td>{String(pnl)}</Td>
                  </Tr>
                ))}
              </TBody>
            </Table>
            <Table>
              <THead>
                <tr>
                  <Th>Sector</Th>
                  <Th>PnL Contrib</Th>
                </tr>
              </THead>
              <TBody>
                {(sectorAttribution.length > 0 ? sectorAttribution : [["Unknown", 0]]).map(([sector, pnl]) => (
                  <Tr key={sector}>
                    <Td>{sector}</Td>
                    <Td>{String(pnl)}</Td>
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
