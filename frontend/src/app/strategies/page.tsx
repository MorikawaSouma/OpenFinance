"use client";

import Link from "next/link";

import { EmptyState } from "@/components/common/empty-state";
import { useCatalogSummaryState } from "@/components/providers/catalog-summary-provider";
import { Badge } from "@/components/ui/badge";
import { Card, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";

export default function StrategiesPage() {
  const { strategies, isStrategiesBootstrapPending } = useCatalogSummaryState();

  return (
    <Card>
      <CardHeader>
        <CardTitle>Strategies</CardTitle>
      </CardHeader>

      {isStrategiesBootstrapPending ? (
        <div className="space-y-2">
          {Array.from({ length: 6 }).map((_, i) => (
            <Skeleton key={i} className="h-12 w-full" />
          ))}
        </div>
      ) : strategies.length === 0 ? (
        <EmptyState title="No strategies yet" description="Run pipeline/backtest to register strategy versions." />
      ) : (
        <div className="space-y-2">
          {strategies.map((item) => (
            <Link
              key={`${item.strategy_id}-${item.strategy_version}`}
              href={`/strategies/${item.strategy_version}`}
              className="block rounded-xl border border-border p-3 hover:bg-muted/10"
            >
              <div className="flex items-center justify-between gap-2">
                <p className="text-sm font-semibold">{item.strategy_version}</p>
                <Badge variant={item.status === "registered" ? "success" : "muted"}>{item.status}</Badge>
              </div>
              <p className="mt-1 text-xs text-muted-foreground">{item.notes}</p>
            </Link>
          ))}
        </div>
      )}
    </Card>
  );
}
