"use client";

import { useTheme } from "next-themes";

import { EmptyState } from "@/components/common/empty-state";
import { useRiskApprovalActions, useRiskApprovalState } from "@/components/providers/risk-approval-provider";
import { useWorkbenchShellState } from "@/components/providers/workbench-shell-provider";
import { useWorkbench } from "@/components/providers/workbench-provider";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TBody, Td, Th, THead, Tr } from "@/components/ui/table";
import { API_BASE } from "@/lib/api";

export default function SettingsPage() {
  const { loadingCore } = useWorkbench();
  const { mode } = useWorkbenchShellState();
  const { riskSnapshot: risk, approvals } = useRiskApprovalState();
  const { requestApproval, approveApproval, enableApproval, revokeApproval } = useRiskApprovalActions();
  const { resolvedTheme } = useTheme();

  if (loadingCore) {
    return (
      <div className="grid gap-4">
        <Skeleton className="h-28 w-full" />
        <Skeleton className="h-28 w-full" />
      </div>
    );
  }

  if (!risk) {
    return <EmptyState title="Settings unavailable" description="Backend status is unavailable. Retry later." />;
  }

  return (
    <div className="grid gap-4">
      <Card>
        <CardHeader>
          <CardTitle>Workspace Settings</CardTitle>
          <CardDescription>Environment and UX mode information.</CardDescription>
        </CardHeader>
        <CardContent className="grid gap-2 text-sm md:grid-cols-2">
          <p>API base: <span className="font-medium">{API_BASE}</span></p>
          <p>Theme: <span className="font-medium">{resolvedTheme === "dark" ? "Dark" : "Light"}</span></p>
          <p>Mode: <span className="font-medium">{mode}</span></p>
          <p>Product posture: <span className="font-medium">User-first, internals hidden by default</span></p>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Governance Defaults</CardTitle>
          <CardDescription>Built-in production-safe defaults.</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-wrap gap-2">
          <Badge variant="success">Live trading disabled by default</Badge>
          <Badge variant="muted">Dataset versioning required</Badge>
          <Badge variant="muted">Run registry enabled</Badge>
          <Badge variant="muted">Audit chain enabled</Badge>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>RiskGate Approval Console</CardTitle>
          <CardDescription>
            State machine: requested -&gt; pending -&gt; approved -&gt; enabled -&gt; revoked/expired.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex flex-wrap gap-2">
            <Button variant="outline" onClick={() => void requestApproval({ target: "paper_trading" })}>
              Request Paper Unlock
            </Button>
            <Button onClick={() => void requestApproval({ target: "live_trading" })}>
              Request Live Unlock
            </Button>
            <Badge variant="muted">pending: {risk.pending_approval_count ?? 0}</Badge>
            <Badge variant="muted">live state: {risk.live_approval_state ?? "none"}</Badge>
            <Badge variant="muted">paper state: {risk.paper_approval_state ?? "none"}</Badge>
          </div>

          {approvals.length === 0 ? (
            <EmptyState title="No approval requests" description="Request unlock from buttons above." />
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
    </div>
  );
}



