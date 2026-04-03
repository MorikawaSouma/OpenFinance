"use client";

import Link from "next/link";

import { EmptyState } from "@/components/common/empty-state";
import { useCatalogSummaryState } from "@/components/providers/catalog-summary-provider";
import { Card, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";

export default function DatasetsPage() {
  const { datasets, isDatasetsBootstrapPending } = useCatalogSummaryState();

  return (
    <Card>
      <CardHeader>
        <CardTitle>Datasets</CardTitle>
      </CardHeader>

      {isDatasetsBootstrapPending ? (
        <div className="space-y-2">
          {Array.from({ length: 6 }).map((_, i) => (
            <Skeleton key={i} className="h-12 w-full" />
          ))}
        </div>
      ) : datasets.length === 0 ? (
        <EmptyState title="No datasets yet" description="Generate a mock dataset from Dashboard first." />
      ) : (
        <div className="space-y-2">
          {datasets.map((item) => (
            <Link
              key={item.dataset_version}
              href={`/datasets/${item.dataset_version}`}
              className="block rounded-xl border border-border p-3 hover:bg-muted/10"
            >
              <p className="text-sm font-semibold">{item.dataset_version}</p>
              <p className="text-xs text-muted-foreground">schema {item.schema_version} | seed {item.seed}</p>
            </Link>
          ))}
        </div>
      )}
    </Card>
  );
}
