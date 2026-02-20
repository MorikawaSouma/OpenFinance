"use client";

import { useCallback, useEffect, useState } from "react";

import { EmptyState } from "@/components/common/empty-state";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { api } from "@/lib/api";
import type { EvidencePack, EvidencePackSummary } from "@/lib/types";

export default function EvidencePage() {
  const [queryPackId, setQueryPackId] = useState<string | null>(null);
  const [querySourceId, setQuerySourceId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [packs, setPacks] = useState<EvidencePackSummary[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [activePack, setActivePack] = useState<EvidencePack | null>(null);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    setQueryPackId(params.get("pack"));
    setQuerySourceId(params.get("source"));
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const rows = await api.getEvidencePacks();
      setPacks(rows);
      if (rows.length > 0) {
        const validQueryId = queryPackId && rows.some((row) => row.id === queryPackId) ? queryPackId : null;
        const nextId = validQueryId ?? activeId ?? rows[0].id;
        setActiveId(nextId);
        setActivePack(await api.getEvidencePack(nextId));
      } else {
        setActivePack(null);
      }
    } finally {
      setLoading(false);
    }
  }, [activeId, queryPackId]);

  useEffect(() => {
    void load();
  }, [load]);

  async function openPack(id: string) {
    setActiveId(id);
    setActivePack(await api.getEvidencePack(id));
  }

  return (
    <div className="grid gap-4 xl:grid-cols-12">
      <Card className="xl:col-span-4">
        <CardHeader>
          <CardTitle>Evidence Packs</CardTitle>
          <CardDescription>Persistent retrieval results from local corpus.</CardDescription>
        </CardHeader>
        <CardContent>
          {loading ? (
            <div className="space-y-2">
              {Array.from({ length: 6 }).map((_, i) => (
                <Skeleton key={i} className="h-12 w-full" />
              ))}
            </div>
          ) : packs.length === 0 ? (
            <EmptyState title="No packs yet" description="Run chat or pipeline to generate evidence packs." />
          ) : (
            <div className="space-y-2">
              {packs.map((pack) => (
                <button
                  key={pack.id}
                  onClick={() => void openPack(pack.id)}
                  className={`w-full rounded-lg border p-2 text-left text-xs ${
                    activeId === pack.id ? "border-primary bg-primary/10" : "hover:bg-accent/60"
                  }`}
                >
                  <p className="line-clamp-2 font-medium">{pack.query}</p>
                  <p className="mt-1 text-muted-foreground">
                    {new Date(pack.created_at).toLocaleString()} | sources: {pack.source_count}
                  </p>
                </button>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      <Card className="xl:col-span-8">
        <CardHeader>
          <CardTitle>Evidence Pack Viewer</CardTitle>
          <CardDescription>Inspect source snippets, timestamps, and credibility.</CardDescription>
        </CardHeader>
        <CardContent>
          {!activePack ? (
            <EmptyState title="Select a pack" description="Choose an evidence pack from the left list." />
          ) : (
            <div className="space-y-3">
              <div className="rounded-lg border p-3 text-xs text-muted-foreground">
                <p className="font-semibold text-foreground">{activePack.query}</p>
                <p>created_at: {new Date(activePack.created_at).toLocaleString()}</p>
                <p>credibility_score: {activePack.credibility_score}</p>
                <p>time_relevance: {activePack.time_relevance}</p>
                {activePack.credibility_breakdown ? (
                  <details className="mt-2 rounded border bg-background p-2">
                    <summary className="cursor-pointer text-xs font-semibold">Credibility Breakdown (Pack)</summary>
                    <pre className="mt-1 overflow-x-auto text-[11px]">
                      {JSON.stringify(activePack.credibility_breakdown, null, 2)}
                    </pre>
                  </details>
                ) : null}
              </div>
              {activePack.sources.map((source) => (
                <div
                  key={source.source_id}
                  className={`rounded-lg border p-3 ${querySourceId === source.source_id ? "border-primary bg-primary/5" : ""}`}
                >
                  <p className="text-sm font-semibold">{source.title}</p>
                  <p className="text-xs text-muted-foreground">
                    ts: {(source.published_at ?? source.timestamp) ? new Date(source.published_at ?? source.timestamp ?? "").toLocaleString() : "n/a"} | credibility:{" "}
                    {source.credibility_score}
                  </p>
                  <p className="text-xs text-muted-foreground">source_type: {source.source_type ?? "unknown"}</p>
                  <p className="mt-1 break-all text-[11px] text-muted-foreground">
                    source: {source.uri ?? source.url ?? "n/a"}
                  </p>
                  {source.full_text_ref ? (
                    <p className="break-all text-[11px] text-muted-foreground">full_text_ref: {source.full_text_ref}</p>
                  ) : null}
                  <p className="mt-2 text-xs">{source.snippet}</p>
                  {source.credibility_breakdown ? (
                    <details className="mt-2 rounded border bg-background p-2">
                      <summary className="cursor-pointer text-xs font-semibold">Breakdown</summary>
                      <pre className="mt-1 overflow-x-auto text-[11px]">
                        {JSON.stringify(source.credibility_breakdown, null, 2)}
                      </pre>
                    </details>
                  ) : null}
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
