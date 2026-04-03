"use client";

import { useEffect, useMemo, type ReactNode } from "react";

import { ToastViewport } from "@/components/ui/toast";
import { readLegacyModeFromStorage, useWorkbenchShellStore } from "@/lib/workbench-shell-store";

export function WorkbenchShellProvider({ children }: { children: ReactNode }) {
  const hydrateLegacyMode = useWorkbenchShellStore((state) => state.hydrateLegacyMode);
  const toasts = useWorkbenchShellStore((state) => state.toasts);
  const dismissToast = useWorkbenchShellStore((state) => state.dismissToast);

  useEffect(() => {
    // Shell ownership is now stable here: hydrate persisted mode once and host the live toast viewport.
    hydrateLegacyMode(readLegacyModeFromStorage());
  }, [hydrateLegacyMode]);

  return (
    <>
      {children}
      <ToastViewport items={toasts} onDismiss={dismissToast} />
    </>
  );
}

export function useWorkbenchShellState() {
  const mode = useWorkbenchShellStore((state) => state.mode);
  const toasts = useWorkbenchShellStore((state) => state.toasts);
  const legacyModeHydrated = useWorkbenchShellStore((state) => state.legacyModeHydrated);

  return useMemo(
    () => ({
      mode,
      toasts,
      legacyModeHydrated,
    }),
    [legacyModeHydrated, mode, toasts]
  );
}

export function useWorkbenchShellActions() {
  const setMode = useWorkbenchShellStore((state) => state.setMode);
  const pushToast = useWorkbenchShellStore((state) => state.pushToast);
  const dismissToast = useWorkbenchShellStore((state) => state.dismissToast);
  const clearToasts = useWorkbenchShellStore((state) => state.clearToasts);

  return useMemo(
    () => ({
      setMode,
      pushToast,
      dismissToast,
      clearToasts,
    }),
    [clearToasts, dismissToast, pushToast, setMode]
  );
}
