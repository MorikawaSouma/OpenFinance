"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { EmptyState } from "@/components/common/empty-state";
import { useWorkbenchShellActions } from "@/components/providers/workbench-shell-provider";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { api } from "@/lib/api";
import type { StrategyDetail } from "@/lib/types";

export default function StrategyDetailPage() {
  const params = useParams<{ strategyVersion: string }>();
  const strategyVersion = String(params.strategyVersion ?? "");
  const { pushToast } = useWorkbenchShellActions();
  const [loading, setLoading] = useState(true);
  const [detail, setDetail] = useState<StrategyDetail | null>(null);

  const load = useCallback(async () => {
    if (!strategyVersion) return;
    setLoading(true);
    try {
      const data = await api.getStrategy(strategyVersion);
      setDetail(data as StrategyDetail);
    } catch (err) {
      setDetail(null);
      pushToast("Load strategy failed", err instanceof Error ? err.message : "Unknown error", "error");
    } finally {
      setLoading(false);
    }
  }, [pushToast, strategyVersion]);

  useEffect(() => {
    void load();
  }, [load]);

  if (loading) {
    return (
      <div className="grid gap-4">
        <Skeleton className="h-28 w-full" />
        <Skeleton className="h-44 w-full" />
      </div>
    );
  }

  if (!detail) {
    return (
      <EmptyState
        title="Strategy not found"
        description="The strategy version may be unavailable. Retry or generate a new run."
      />
    );
  }

  return (
    <div className="grid gap-4">
      <Card>
        <CardHeader>
          <div>
            <CardTitle>Strategy Detail</CardTitle>
            <CardDescription>{detail.spec.strategy_version}</CardDescription>
          </div>
          <div className="flex gap-2">
            <Button variant="outline" onClick={() => void load()}>
              Retry
            </Button>
            <Link href="/strategies">
              <Button variant="secondary">Back to List</Button>
            </Link>
          </div>
        </CardHeader>
        <CardContent className="grid gap-2 text-sm md:grid-cols-2">
          <p>source: <span className="font-medium">{detail.source}</span></p>
          <p>version: <span className="font-medium">{detail.spec.strategy_version}</span></p>
          <p>strategy_id: <span className="font-medium">{detail.spec.strategy_id}</span></p>
          <p>market: <span className="font-medium">{detail.spec.market}</span></p>
          <p>strategy_family: <span className="font-medium">{detail.spec.strategy_family}</span></p>
          <p>rebalance: <span className="font-medium">{detail.spec.rebalance}</span></p>
          <p>lookback_days: <span className="font-medium">{detail.spec.lookback_days}</span></p>
          <p>position_sizing: <span className="font-medium">{detail.spec.position_sizing}</span></p>
          <p>risk_budget: <span className="font-medium">{detail.spec.risk_budget}</span></p>
          <p>max_position: <span className="font-medium">{detail.spec.max_position}</span></p>
          <p>leverage_limit: <span className="font-medium">{detail.spec.leverage_limit}</span></p>
          <p>simulation_only: <span className="font-medium">{detail.spec.simulation_only ? "true" : "false"}</span></p>
          {detail.created_at ? <p>created_at: <span className="font-medium">{detail.created_at}</span></p> : null}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <div>
            <CardTitle>Strategy Semantics</CardTitle>
            <CardDescription>Product-facing spec object used for inspection and downstream compilation.</CardDescription>
          </div>
        </CardHeader>
        <div className="grid gap-3 p-6 pt-0 text-sm">
          <div>
            <p className="font-medium">Rationale</p>
            <p className="mt-1 text-xs text-muted-foreground">{detail.spec.rationale}</p>
          </div>
          <div>
            <p className="font-medium">Constraints</p>
            <pre className="mt-2 overflow-x-auto rounded-lg border border-border p-3 text-xs text-muted-foreground">
              {JSON.stringify(detail.spec.constraints, null, 2)}
            </pre>
          </div>
          <div>
            <p className="font-medium">Factor Weights</p>
            <pre className="mt-2 overflow-x-auto rounded-lg border border-border p-3 text-xs text-muted-foreground">
              {JSON.stringify(detail.spec.factor_weights, null, 2)}
            </pre>
          </div>
        </div>
        <p className="mt-2 text-xs text-muted-foreground">{detail.notes}</p>
      </Card>

      <Card>
        <CardHeader>
          <div>
            <CardTitle>Circuit Breaker</CardTitle>
            <CardDescription>Visible stop-trading rule in strategy spec.</CardDescription>
          </div>
        </CardHeader>
        <CardContent className="grid gap-2 text-sm md:grid-cols-2">
          <p>
            enabled: <span className="font-medium">{detail.spec.circuit_breaker?.enabled ? "true" : "false"}</span>
          </p>
          <p>
            rule.type:{" "}
            <span className="font-medium">{detail.spec.circuit_breaker?.rule?.type ?? "-"}</span>
          </p>
          <p>
            rule.threshold:{" "}
            <span className="font-medium">{String(detail.spec.circuit_breaker?.rule?.threshold ?? "-")}</span>
          </p>
          <p>
            rule.cool_down_days:{" "}
            <span className="font-medium">{String(detail.spec.circuit_breaker?.rule?.cool_down_days ?? "-")}</span>
          </p>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <div>
            <CardTitle>Failure Regimes</CardTitle>
            <CardDescription>Expected market environments where strategy may degrade.</CardDescription>
          </div>
        </CardHeader>
        <CardContent>
          {!Array.isArray(detail.spec.failure_regimes) || detail.spec.failure_regimes.length === 0 ? (
            <p className="text-xs text-muted-foreground">No failure regimes recorded.</p>
          ) : (
            <div className="flex flex-wrap gap-1">
              {detail.spec.failure_regimes.map((item) => (
                <Badge key={item} variant="muted">
                  {item}
                </Badge>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <div>
            <CardTitle>Evidence Links</CardTitle>
            <CardDescription>References attached to the durable strategy spec.</CardDescription>
          </div>
        </CardHeader>
        <CardContent>
          {detail.spec.evidence_refs.length === 0 ? (
            <p className="text-xs text-muted-foreground">No evidence links recorded.</p>
          ) : (
            <div className="flex flex-wrap gap-1">
              {detail.spec.evidence_refs.map((item) => (
                <Badge key={item} variant="outline">
                  {item}
                </Badge>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
