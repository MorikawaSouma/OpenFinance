"use client";

import { create } from "zustand";

import type { SseEvent } from "@/lib/types";

type SseConnectionState = "connecting" | "open" | "closed" | "error" | "reconnecting";

type WorkbenchChatStoreState = {
  events: SseEvent[];
  sseConnectionState: SseConnectionState;
  prependEvents: (rows: SseEvent[]) => void;
  setSseConnectionState: (next: SseConnectionState) => void;
};

// Legacy name only: after the WorkbenchProvider removal, this is the coordinator-owned
// raw event buffer and connection-state store that /chat and domain providers still read.
export const useWorkbenchChatStore = create<WorkbenchChatStoreState>()((set) => ({
  events: [],
  sseConnectionState: "connecting",

  prependEvents: (rows) => {
    if (rows.length === 0) return;
    set((state) => ({
      events: [...rows, ...state.events].slice(0, 120),
    }));
  },

  setSseConnectionState: (next) => {
    set({ sseConnectionState: next });
  },
}));
