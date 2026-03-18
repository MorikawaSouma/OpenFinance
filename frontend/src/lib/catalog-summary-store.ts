"use client";

import { create } from "zustand";

import type { DatasetEntry, RunSummary, StrategySummary } from "@/lib/types";

export type CatalogSummaryOwnership = "placeholder" | "legacy-workbench";

type CatalogSummaryStoreState = {
  ownership: CatalogSummaryOwnership;
  datasets: DatasetEntry[];
  runs: RunSummary[];
  strategies: StrategySummary[];
  lastDatasetsRefreshAt: string | null;
  lastRunsRefreshAt: string | null;
  lastStrategiesRefreshAt: string | null;
  markOwnership: (next: CatalogSummaryOwnership) => void;
  setDatasets: (rows: DatasetEntry[], refreshedAt?: string | null) => void;
  setRuns: (rows: RunSummary[], refreshedAt?: string | null) => void;
  setStrategies: (rows: StrategySummary[], refreshedAt?: string | null) => void;
  clearCatalogSummary: () => void;
};

export const useCatalogSummaryStore = create<CatalogSummaryStoreState>()((set) => ({
  ownership: "placeholder",
  datasets: [],
  runs: [],
  strategies: [],
  lastDatasetsRefreshAt: null,
  lastRunsRefreshAt: null,
  lastStrategiesRefreshAt: null,

  markOwnership: (next) => {
    set({ ownership: next });
  },

  setDatasets: (rows, refreshedAt) => {
    set({
      datasets: rows,
      lastDatasetsRefreshAt: refreshedAt ?? new Date().toISOString(),
    });
  },

  setRuns: (rows, refreshedAt) => {
    set({
      runs: rows,
      lastRunsRefreshAt: refreshedAt ?? new Date().toISOString(),
    });
  },

  setStrategies: (rows, refreshedAt) => {
    set({
      strategies: rows,
      lastStrategiesRefreshAt: refreshedAt ?? new Date().toISOString(),
    });
  },

  clearCatalogSummary: () => {
    set({
      datasets: [],
      runs: [],
      strategies: [],
      lastDatasetsRefreshAt: null,
      lastRunsRefreshAt: null,
      lastStrategiesRefreshAt: null,
    });
  },
}));
