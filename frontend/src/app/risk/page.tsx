"use client";

import { ShieldAlert } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

import { EmptyState } from "@/components/common/empty-state";
import { useRiskApprovalActions, useRiskApprovalState } from "@/components/providers/risk-approval-provider";
import { useWorkbenchShellActions, useWorkbenchShellState } from "@/components/providers/workbench-shell-provider";
import { useWorkbench } from "@/components/providers/workbench-provider";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TBody, Td, Th, THead, Tr } from "@/components/ui/table";
import { api } from "@/lib/api";
import type { RiskEventRow, SimBrokerLog } from "@/lib/types";

const environments = [
  { env: "Research", detail: "Idea exploration, no order flow." },
  { env: "Backtest", detail: "Versioned replay with reproducible metrics." },
  { env: "Paper", detail: "Same path as live, no real execution." },
  { env: "Live", detail: "Default locked, approval required." },
];

export default function RiskPage() {
  const { loadingCore } = useWorkbench();
  const { mode } = useWorkbenchShellState();
  const { pushToast } = useWorkbenchShellActions();
  const { riskSnapshot: risk, approvals } = useRiskApprovalState();
  const {
    setKillSwitch,
    setLiveUnlock,
    requestApproval,
    approveApproval,
    enableApproval,
    revokeApproval,
  } = useRiskApprovalActions();
  const [unlockOpen, setUnlockOpen] = useState(false);
  const [logsLoading, setLogsLoading] = useState(false);
  const [liveLogs, setLiveLogs] = useState<SimBrokerLog[]>([]);
  const [riskEventsLoading, setRiskEventsLoading] = useState(false);
  const [riskEvents, setRiskEvents] = useState<RiskEventRow[]>([]);
  const [shockRunning, setShockRunning] = useState(false);

  const drawdownPct = (((risk?.current_drawdown ?? 0) * 100)).toFixed(2);
  const volPct = (((risk?.current_volatility ?? 0) * 100)).toFixed(2);
  const limitPct = (((risk?.max_account_drawdown_limit ?? 0) * 100)).toFixed(2);
  const volLimitPct = (((risk?.abnormal_volatility_limit ?? 0) * 100)).toFixed(2);
  const riskStatus = (risk?.risk_status ?? "normal").toLowerCase();
  const riskStatusVariant: "destructive" | "warning" | "success" =
    riskStatus === "blocked" ? "destructive" : riskStatus === "warn" ? "warning" : "success";
  const currentEquity = Number(risk?.current_equity ?? 1_000_000);
  const shockTargetEquity = Math.max(1, Number((currentEquity * 0.94).toFixed(2)));

  const recentEvents = useMemo(() => {
    const fromStatus = Array.isArray(risk?.recent_risk_events) ? risk.recent_risk_events : [];
    return (riskEvents.length > 0 ? riskEvents : fromStatus).slice(0, 20);
  }, [risk?.recent_risk_events, riskEvents]);

  const loadLiveLogs = useCallback(async () => {
    setLogsLoading(true);
    try {
      const rows = await api.getLiveLogs(120);
      setLiveLogs(rows);
    } catch (err) {
      setLiveLogs([]);
      pushToast("Load live logs failed", err instanceof Error ? err.message : "Unknown error", "error");
    } finally {
      setLogsLoading(false);
    }
  }, [pushToast]);

  const loadRiskEvents = useCallback(async () => {
    setRiskEventsLoading(true);
    try {
      const rows = await api.getRiskEvents(80);
      setRiskEvents(rows);
    } catch (err) {
      setRiskEvents([]);
      pushToast("Load risk events failed", err instanceof Error ? err.message : "Unknown error", "error");
    } finally {
      setRiskEventsLoading(false);
    }
  }, [pushToast]);

  useEffect(() => {
    void loadLiveLogs();
    void loadRiskEvents();
  }, [loadLiveLogs, loadRiskEvents]);

  if (loadingCore) {
    return (
      <div className="grid gap-4">
        <Skeleton className="h-24 w-full" />
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }

  if (!risk) {
    return <EmptyState title="Risk status unavailable" description="Retry after backend is healthy." />;
  }

  return (
    <div className="grid gap-4">
      <Card>
        <CardHeader>
          <CardTitle>Risk Gate Status</CardTitle>
          <CardDescription>Live trading is locked by default.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-2">
          <div className="flex items-center gap-2">
            <Badge variant={risk.live_trading_enabled ? "destructive" : "success"}>
              {risk.live_trading_enabled ? "Live Enabled" : "Live Locked"}
            </Badge>
            <Badge variant="muted">mode: {risk.mode}</Badge>
          </div>
          <p className="text-sm">Max order qty: <span className="font-medium">{risk.risk_max_order_qty}</span></p>
          <p className="text-sm">Kill switch: <span className="font-medium">{risk.kill_switch_enabled ? "ON" : "OFF"}</span></p>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Account-level Risk Monitor</CardTitle>
          <CardDescription>Realtime account drawdown/volatility monitoring with auto kill switch.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="grid gap-2 md:grid-cols-4">
            <div className="rounded-lg border p-3">
              <p className="text-xs text-muted-foreground">Status</p>
              <Badge variant={riskStatusVariant} className="mt-1">{riskStatus}</Badge>
            </div>
            <div className="rounded-lg border p-3">
              <p className="text-xs text-muted-foreground">Current Drawdown</p>
              <p className="text-sm font-semibold">{drawdownPct}%</p>
              <p className="text-[11px] text-muted-foreground">limit {limitPct}%</p>
            </div>
            <div className="rounded-lg border p-3">
              <p className="text-xs text-muted-foreground">Rolling Volatility</p>
              <p className="text-sm font-semibold">{volPct}%</p>
              <p className="text-[11px] text-muted-foreground">limit {volLimitPct}%</p>
            </div>
            <div className="rounded-lg border p-3">
              <p className="text-xs text-muted-foreground">Account Equity</p>
              <p className="text-sm font-semibold">{Number(risk.current_equity ?? 0).toLocaleString()}</p>
              <p className="text-[11px] text-muted-foreground">peak {Number(risk.peak_equity ?? 0).toLocaleString()}</p>
            </div>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button variant="outline" onClick={() => void loadRiskEvents()} disabled={riskEventsLoading}>
              {riskEventsLoading ? "Loading..." : "Refresh Risk Events"}
            </Button>
            <Button
              variant="destructive"
              onClick={async () => {
                setShockRunning(true);
                try {
                  await api.updateRiskHeartbeat({
                    account_equity: shockTargetEquity,
                    source: "mock_drawdown_test",
                    metrics: { scenario: "rapid_drawdown", note: "ui_trigger" },
                  });
                  await loadRiskEvents();
                  pushToast("Shock applied", `equity -> ${shockTargetEquity.toLocaleString()}`, "default");
                } catch (err) {
                  pushToast("Shock failed", err instanceof Error ? err.message : "Unknown error", "error");
                } finally {
                  setShockRunning(false);
                }
              }}
              disabled={shockRunning}
            >
              {shockRunning ? "Applying..." : "Simulate >5% Drawdown"}
            </Button>
          </div>
          {riskEventsLoading ? (
            <Skeleton className="h-32 w-full" />
          ) : recentEvents.length === 0 ? (
            <EmptyState title="No risk events" description="System is currently in normal range." />
          ) : (
            <Table>
              <THead>
                <tr>
                  <Th>Time</Th>
                  <Th>Severity</Th>
                  <Th>Type</Th>
                  <Th>Message</Th>
                </tr>
              </THead>
              <TBody>
                {recentEvents.map((row) => (
                  <Tr key={row.event_id}>
                    <Td>{new Date(row.created_at).toLocaleString()}</Td>
                    <Td>
                      <Badge variant={row.severity === "high" ? "destructive" : row.severity === "medium" ? "warning" : "muted"}>
                        {row.severity}
                      </Badge>
                    </Td>
                    <Td>{row.event_type}</Td>
                    <Td>{row.message}</Td>
                  </Tr>
                ))}
              </TBody>
            </Table>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Environment Isolation</CardTitle>
          <CardDescription>Research to Backtest to Paper to Live are separated by risk controls.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-2">
          {environments.map((row) => (
            <div key={row.env} className="rounded-lg border p-3">
              <div className="flex items-center justify-between">
                <p className="text-sm font-semibold">{row.env}</p>
                <Badge variant={row.env === "Live" ? "warning" : "muted"}>
                  {row.env === "Live" ? "Approval Required" : "Open"}
                </Badge>
              </div>
              <p className="mt-1 text-xs text-muted-foreground">{row.detail}</p>
            </div>
          ))}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Live Unlock Entry</CardTitle>
          <CardDescription>UI entry exists, but actual enablement depends on backend policy and approvals.</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-wrap gap-2">
          <Button variant="outline" onClick={() => setUnlockOpen(true)}>
            Request Live Unlock
          </Button>
          <Button variant="secondary" onClick={() => void setLiveUnlock(false)}>
            Lock Live Again
          </Button>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Approval Workflow</CardTitle>
          <CardDescription>request_trade_enable: pending -&gt; approved -&gt; enabled -&gt; revoked/expired.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex flex-wrap gap-2">
            <Button variant="outline" onClick={() => void requestApproval({ target: "paper_trading" })}>
              Request Paper Enable
            </Button>
            <Button onClick={() => void requestApproval({ target: "live_trading" })}>
              Request Sim Live Enable
            </Button>
            <Badge variant="muted">pending: {risk.pending_approval_count ?? 0}</Badge>
            <Badge variant="muted">live state: {risk.live_approval_state ?? "none"}</Badge>
            <Badge variant="muted">paper state: {risk.paper_approval_state ?? "none"}</Badge>
          </div>
          {approvals.length === 0 ? (
            <EmptyState title="No approval request" description="Create one from buttons above." />
          ) : (
            <Table>
              <THead>
                <tr>
                  <Th>Request</Th>
                  <Th>Target</Th>
                  <Th>Status</Th>
                  <Th>Updated</Th>
                  <Th>Action</Th>
                </tr>
              </THead>
              <TBody>
                {approvals.slice(0, 10).map((row) => (
                  <Tr key={row.request_id}>
                    <Td className="text-xs">{row.request_id}</Td>
                    <Td>{row.target}</Td>
                    <Td>{row.status}</Td>
                    <Td>{new Date(row.updated_at).toLocaleString()}</Td>
                    <Td>
                      <div className="flex gap-1">
                        <Button
                          size="sm"
                          variant="secondary"
                          disabled={row.status !== "pending"}
                          onClick={() => void approveApproval(row.request_id)}
                        >
                          Approve
                        </Button>
                        <Button
                          size="sm"
                          variant="outline"
                          disabled={row.status !== "approved"}
                          onClick={() => void enableApproval(row.request_id)}
                        >
                          Enable
                        </Button>
                        <Button
                          size="sm"
                          variant="destructive"
                          disabled={row.status === "revoked" || row.status === "expired"}
                          onClick={() => void revokeApproval(row.request_id)}
                        >
                          Revoke
                        </Button>
                      </div>
                    </Td>
                  </Tr>
                ))}
              </TBody>
            </Table>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Sim Live Trading Logs</CardTitle>
          <CardDescription>Order -&gt; fill -&gt; reconcile logs from SimBrokerAdapter.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex gap-2">
            <Button variant="outline" onClick={() => void loadLiveLogs()} disabled={logsLoading}>
              {logsLoading ? "Loading..." : "Refresh Logs"}
            </Button>
            <Button
              onClick={async () => {
                try {
                  const resp = await api.placeLiveOrder({
                    instrument_id: "sim_us_aapl",
                    side: "buy",
                    quantity: 10,
                    order_type: "market",
                    evidence_pack_id: "ui_manual_live_order",
                  });
                  const status = String(resp.status ?? "");
                  const reason = String(resp.reason ?? "");
                  if (status === "pending_approval" || reason === "pending_approval") {
                    pushToast("Pending approval", "Live order entered pending state.", "default");
                  } else {
                    pushToast("Sim live order sent", `reason=${reason}`, "success");
                  }
                  await loadLiveLogs();
                } catch (err) {
                  pushToast("Sim live order failed", err instanceof Error ? err.message : "Unknown error", "error");
                }
              }}
            >
              Send Sim Live Order
            </Button>
          </div>
          {logsLoading ? (
            <Skeleton className="h-32 w-full" />
          ) : liveLogs.length === 0 ? (
            <EmptyState
              title="No live logs yet"
              description="After approval and enablement, send a sim live order to see lifecycle logs."
            />
          ) : (
            <Table>
              <THead>
                <tr>
                  <Th>Time</Th>
                  <Th>Stage</Th>
                  <Th>Instrument</Th>
                  <Th>Side</Th>
                  <Th>Qty</Th>
                  <Th>Price</Th>
                  <Th>Detail</Th>
                </tr>
              </THead>
              <TBody>
                {liveLogs.slice(0, 40).map((row) => (
                  <Tr key={row.log_id}>
                    <Td>{new Date(row.created_at).toLocaleString()}</Td>
                    <Td>{row.stage}</Td>
                    <Td>{row.instrument_id}</Td>
                    <Td>{row.side}</Td>
                    <Td>{row.quantity}</Td>
                    <Td>{row.price ?? "-"}</Td>
                    <Td>{row.detail}</Td>
                  </Tr>
                ))}
              </TBody>
            </Table>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Kill Switch</CardTitle>
          <CardDescription>Protected high-risk control.</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="rounded-lg border border-destructive/40 bg-destructive/5 p-3">
            <div className="flex items-center gap-2 text-destructive">
              <ShieldAlert className="h-4 w-4" />
              <p className="text-sm font-semibold">High-risk operation</p>
            </div>
            <p className="mt-1 text-xs text-muted-foreground">
              User Mode shows state only. Developer Mode can toggle after explicit confirmation.
            </p>
            <div className="mt-3 flex gap-2">
              <Button
                variant="destructive"
                disabled={mode !== "developer"}
                onClick={async () => {
                  if (!window.confirm("Confirm toggling kill switch?")) return;
                  await setKillSwitch(!risk.kill_switch_enabled);
                }}
              >
                {risk.kill_switch_enabled ? "Turn OFF Kill Switch" : "Turn ON Kill Switch"}
              </Button>
              {mode !== "developer" ? <Badge variant="muted">Enable Developer Mode to operate</Badge> : null}
            </div>
          </div>
        </CardContent>
      </Card>

      <Dialog open={unlockOpen} onOpenChange={setUnlockOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Request Live Unlock</DialogTitle>
            <DialogDescription>
              Production unlock requires approval. Backend policy may still keep live trading locked.
            </DialogDescription>
          </DialogHeader>
          <p className="text-xs text-muted-foreground">
            This is an entry point only. Final status is enforced server-side by risk gate policies.
          </p>
          <DialogFooter>
            <Button variant="outline" onClick={() => setUnlockOpen(false)}>
              Cancel
            </Button>
            <Button
              onClick={async () => {
                await setLiveUnlock(true);
                setUnlockOpen(false);
                pushToast("Approval workflow", "If policy blocks live, state remains locked.");
              }}
            >
              Submit Request
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}



