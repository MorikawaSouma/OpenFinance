"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { EmptyState } from "@/components/common/empty-state";
import { useWorkbench } from "@/components/providers/workbench-provider";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { api } from "@/lib/api";
import type { StrategyDetail } from "@/lib/types";

export default function StrategyDetailPage() {
  const params = useParams<{ strategyVersion: string }>();
  const strategyVersion = String(params.strategyVersion ?? "");
  const { pushToast } = useWorkbench();
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
            <CardDescription>{detail.strategy_version}</CardDescription>
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
          <p>strategy_id: <span className="font-medium">{detail.strategy_id}</span></p>
          <p>version: <span className="font-medium">{detail.strategy_version}</span></p>
          <p>market: <span className="font-medium">{detail.market}</span></p>
          <p>rebalance: <span className="font-medium">{detail.rebalance}</span></p>
          {detail.strategy_family ? (
            <p>strategy_family: <span className="font-medium">{detail.strategy_family}</span></p>
          ) : null}
          {typeof detail.lookback_days === "number" ? (
            <p>lookback_days: <span className="font-medium">{detail.lookback_days}</span></p>
          ) : null}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <div>
            <CardTitle>Risk Constraints</CardTitle>
            <CardDescription>Constraint contract used by backtest and execution.</CardDescription>
          </div>
        </CardHeader>
        <pre className="overflow-x-auto rounded-lg border border-border p-3 text-xs text-muted-foreground">
          {JSON.stringify(detail.risk_constraints, null, 2)}
        </pre>
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
            enabled: <span className="font-medium">{detail.circuit_breaker?.enabled ? "true" : "false"}</span>
          </p>
          <p>
            rule.type:{" "}
            <span className="font-medium">{detail.circuit_breaker?.rule?.type ?? "-"}</span>
          </p>
          <p>
            rule.threshold:{" "}
            <span className="font-medium">{String(detail.circuit_breaker?.rule?.threshold ?? "-")}</span>
          </p>
          <p>
            rule.cool_down_days:{" "}
            <span className="font-medium">{String(detail.circuit_breaker?.rule?.cool_down_days ?? "-")}</span>
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
          {!Array.isArray(detail.failure_regimes) || detail.failure_regimes.length === 0 ? (
            <p className="text-xs text-muted-foreground">No failure regimes recorded.</p>
          ) : (
            <div className="flex flex-wrap gap-1">
              {detail.failure_regimes.map((item) => (
                <Badge key={item} variant="muted">
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
