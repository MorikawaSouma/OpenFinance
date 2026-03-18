"use client";

import { createContext, useContext, useMemo, type ReactNode } from "react";

import { useCatalogSummaryStore } from "@/lib/catalog-summary-store";

type CatalogSummaryActions = {
  refreshDatasets: () => Promise<void>;
  refreshRuns: () => Promise<void>;
  refreshStrategies: () => Promise<void>;
};

const CatalogSummaryActionsContext = createContext<CatalogSummaryActions | null>(null);

export function CatalogSummaryProvider({ children }: { children: ReactNode }) {
  const actions = useMemo<CatalogSummaryActions>(
    () => ({
      // Placeholders only. Group 1 does not replace legacy catalog fetch behavior yet.
      refreshDatasets: async () => undefined,
      refreshRuns: async () => undefined,
      refreshStrategies: async () => undefined,
    }),
    []
  );

  return <CatalogSummaryActionsContext.Provider value={actions}>{children}</CatalogSummaryActionsContext.Provider>;
}

export function useCatalogSummaryState() {
  return useCatalogSummaryStore((state) => ({
    ownership: state.ownership,
    datasets: state.datasets,
    runs: state.runs,
    strategies: state.strategies,
    lastDatasetsRefreshAt: state.lastDatasetsRefreshAt,
    lastRunsRefreshAt: state.lastRunsRefreshAt,
    lastStrategiesRefreshAt: state.lastStrategiesRefreshAt,
  }));
}

export function useCatalogSummaryActions() {
  const ctx = useContext(CatalogSummaryActionsContext);
  if (!ctx) {
    throw new Error("useCatalogSummaryActions must be used within CatalogSummaryProvider");
  }
  return ctx;
}
