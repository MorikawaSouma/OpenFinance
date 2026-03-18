"use client";

import { useEffect, type ReactNode } from "react";

import { ToastViewport } from "@/components/ui/toast";
import { readLegacyModeFromStorage, useWorkbenchShellStore } from "@/lib/workbench-shell-store";

export function WorkbenchShellProvider({ children }: { children: ReactNode }) {
  const hydrateLegacyMode = useWorkbenchShellStore((state) => state.hydrateLegacyMode);
  const toasts = useWorkbenchShellStore((state) => state.toasts);
  const dismissToast = useWorkbenchShellStore((state) => state.dismissToast);

  useEffect(() => {
    // Group 2A moves live mode + toast ownership into the shell store while chat/pipeline behavior stays legacy-backed.
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
  return useWorkbenchShellStore((state) => ({
    mode: state.mode,
    toasts: state.toasts,
    legacyModeHydrated: state.legacyModeHydrated,
  }));
}

export function useWorkbenchShellActions() {
  return useWorkbenchShellStore((state) => ({
    setMode: state.setMode,
    pushToast: state.pushToast,
    dismissToast: state.dismissToast,
    clearToasts: state.clearToasts,
  }));
}
