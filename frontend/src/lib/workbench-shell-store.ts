"use client";

import { create } from "zustand";

import type { ToastItem } from "@/components/ui/toast";
import type { Mode } from "@/lib/types";

const MAX_TOASTS = 4;

function uid() {
  return Math.random().toString(36).slice(2, 10);
}

export function readLegacyModeFromStorage(): Mode | null {
  if (typeof window === "undefined") return null;
  const value = localStorage.getItem("of_mode");
  return value === "developer" || value === "user" ? value : null;
}

function persistLegacyMode(next: Mode) {
  if (typeof window === "undefined") return;
  localStorage.setItem("of_mode", next);
}

type WorkbenchShellStoreState = {
  mode: Mode;
  toasts: ToastItem[];
  legacyModeHydrated: boolean;
  setMode: (next: Mode) => void;
  hydrateLegacyMode: (next: Mode | null) => void;
  pushToast: (title: string, description?: string, variant?: ToastItem["variant"]) => string;
  dismissToast: (id: string) => void;
  clearToasts: () => void;
};

export const useWorkbenchShellStore = create<WorkbenchShellStoreState>()((set, get) => ({
  mode: "user",
  toasts: [],
  legacyModeHydrated: false,

  setMode: (next) => {
    persistLegacyMode(next);
    set({ mode: next });
  },

  hydrateLegacyMode: (next) => {
    set((state) => ({
      mode: next ?? state.mode,
      legacyModeHydrated: true,
    }));
  },

  pushToast: (title, description, variant) => {
    const id = uid();
    set((state) => ({
      toasts: [...state.toasts, { id, title, description, variant }].slice(-MAX_TOASTS),
    }));
    if (typeof window !== "undefined") {
      window.setTimeout(() => {
        get().dismissToast(id);
      }, 3500);
    }
    return id;
  },

  dismissToast: (id) => {
    set((state) => ({
      toasts: state.toasts.filter((item) => item.id !== id),
    }));
  },

  clearToasts: () => {
    set({ toasts: [] });
  },
}));
