"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { EmptyState } from "@/components/common/empty-state";
import { useWorkbenchShellActions } from "@/components/providers/workbench-shell-provider";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { api } from "@/lib/api";
import type { DatasetEntry } from "@/lib/types";

function formatPct(v: unknown): string {
  if (typeof v !== "number") return "-";
  return `${(v * 100).toFixed(2)}%`;
}

export default function DatasetDetailPage() {
  const params = useParams<{ datasetVersion: string }>();
  const datasetVersion = String(params.datasetVersion ?? "");
  const { pushToast } = useWorkbenchShellActions();
  const [loading, setLoading] = useState(true);
  const [dataset, setDataset] = useState<DatasetEntry | null>(null);

  const load = useCallback(async () => {
    if (!datasetVersion) return;
    setLoading(true);
    try {
      setDataset(await api.getDataset(datasetVersion));
    } catch (err) {
      setDataset(null);
      pushToast("Load dataset failed", err instanceof Error ? err.message : "Unknown error", "error");
    } finally {
      setLoading(false);
    }
  }, [datasetVersion, pushToast]);

  useEffect(() => {
    void load();
  }, [load]);

  if (loading) {
    return (
      <div className="grid gap-4">
        <Skeleton className="h-28 w-full" />
        <Skeleton className="h-44 w-full" />
        <Skeleton className="h-44 w-full" />
      </div>
    );
  }

  if (!dataset) {
    return (
      <EmptyState
        title="Dataset not found"
        description="The dataset version may be missing. Retry or generate a new dataset."
      />
    );
  }

  const quality = dataset.quality_report ?? {};

  return (
    <div className="grid gap-4">
      <Card>
        <CardHeader>
          <div>
            <CardTitle>Dataset Detail</CardTitle>
            <CardDescription>{dataset.dataset_version}</CardDescription>
          </div>
          <div className="flex gap-2">
            <Button variant="outline" onClick={() => void load()}>
              Retry
            </Button>
            <Link href="/datasets">
              <Button variant="secondary">Back to List</Button>
            </Link>
          </div>
        </CardHeader>
        <div className="grid gap-2 text-sm md:grid-cols-2">
          <p>dataset_id: <span className="font-medium">{dataset.dataset_id}</span></p>
          <p>schema_version: <span className="font-medium">{dataset.schema_version}</span></p>
          <p>seed: <span className="font-medium">{dataset.seed}</span></p>
          <p>artifact: <span className="font-medium">{dataset.artifact_path}</span></p>
        </div>
      </Card>

      <Card>
        <CardHeader>
          <div>
            <CardTitle>Quality Report</CardTitle>
            <CardDescription>Missing, delayed, backfilled, and outlier statistics.</CardDescription>
          </div>
        </CardHeader>
        <div className="grid gap-2 md:grid-cols-3">
          <div className="rounded-lg border border-border p-3">
            <p className="text-xs text-muted-foreground">Missing rate</p>
            <p className="text-sm font-semibold">{formatPct(quality.missing_rate)}</p>
          </div>
          <div className="rounded-lg border border-border p-3">
            <p className="text-xs text-muted-foreground">Delayed rate</p>
            <p className="text-sm font-semibold">{formatPct(quality.delayed_rate)}</p>
          </div>
          <div className="rounded-lg border border-border p-3">
            <p className="text-xs text-muted-foreground">Backfill rate</p>
            <p className="text-sm font-semibold">{formatPct(quality.backfill_rate)}</p>
          </div>
          <div className="rounded-lg border border-border p-3">
            <p className="text-xs text-muted-foreground">Outlier rate</p>
            <p className="text-sm font-semibold">{formatPct(quality.outlier_rate)}</p>
          </div>
          <div className="rounded-lg border border-border p-3">
            <p className="text-xs text-muted-foreground">Total rows</p>
            <p className="text-sm font-semibold">
              {typeof quality.total_rows === "number" ? quality.total_rows : "-"}
            </p>
          </div>
          <div className="rounded-lg border border-border p-3">
            <p className="text-xs text-muted-foreground">Survivorship bias</p>
            <Badge variant={quality.survivorship_bias_enabled ? "warning" : "success"}>
              {quality.survivorship_bias_enabled ? "enabled" : "disabled"}
            </Badge>
            <p className="mt-1 text-xs text-muted-foreground">risk: {String(quality.survivorship_bias_risk ?? "-")}</p>
          </div>
        </div>
      </Card>

      <Card>
        <CardHeader>
          <div>
            <CardTitle>Lineage</CardTitle>
            <CardDescription>Data contract lineage and generation config.</CardDescription>
          </div>
        </CardHeader>
        <details className="rounded-lg border border-border p-3">
          <summary className="cursor-pointer text-sm font-medium">generation_config</summary>
          <pre className="mt-2 overflow-x-auto text-xs text-muted-foreground">
            {JSON.stringify(dataset.generation_config, null, 2)}
          </pre>
        </details>
        <details className="mt-2 rounded-lg border border-border p-3">
          <summary className="cursor-pointer text-sm font-medium">lineage</summary>
          <pre className="mt-2 overflow-x-auto text-xs text-muted-foreground">
            {JSON.stringify(dataset.lineage, null, 2)}
          </pre>
        </details>
      </Card>
    </div>
  );
}
