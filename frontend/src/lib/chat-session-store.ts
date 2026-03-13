"use client";

import { create } from "zustand";
import { createJSONStorage, persist } from "zustand/middleware";

import type { ChatResponse, ChatTurn } from "@/lib/types";

const MAX_PERSISTED_MESSAGES = 20;

export type StoredChatPresentation = {
  messageId: string;
  mode: string;
  language: string;
  cards: ChatResponse["cards"];
  debug: Record<string, unknown>;
  traceId: string;
  evidencePackId: string;
};

export type StoredChatMessage = ChatTurn & {
  id: string;
  presentation?: StoredChatPresentation;
};

type SessionMessages = {
  updatedAt: string;
  turns: StoredChatMessage[];
};

type ChatSessionStoreState = {
  sessions: Record<string, SessionMessages>;
  upsertFromResponse: (response: ChatResponse, maxMessages?: number) => void;
  hydrateSessionTurns: (sessionId: string, turns: ChatTurn[], maxMessages?: number) => void;
  clearSession: (sessionId: string) => void;
};

export function buildMessageId(turn: ChatTurn) {
  return `${String(turn.role || "assistant")}:${String(turn.created_at || "")}`;
}

function toStoredTurn(turn: ChatTurn, existing?: StoredChatMessage): StoredChatMessage {
  return {
    ...turn,
    id: buildMessageId(turn),
    presentation: existing?.presentation,
  };
}

function trimTurns(turns: StoredChatMessage[], maxMessages = MAX_PERSISTED_MESSAGES) {
  if (turns.length <= maxMessages) return turns;
  return turns.slice(-maxMessages);
}

function dedupeTurns(turns: StoredChatMessage[]) {
  const map = new Map<string, StoredChatMessage>();
  const order: string[] = [];
  for (const turn of turns) {
    if (!map.has(turn.id)) order.push(turn.id);
    map.set(turn.id, turn);
  }
  return order.map((id) => map.get(id)).filter((row): row is StoredChatMessage => Boolean(row));
}

export const useChatSessionStore = create<ChatSessionStoreState>()(
  persist(
    (set, get) => ({
      sessions: {},

      upsertFromResponse: (response: ChatResponse, maxMessages = MAX_PERSISTED_MESSAGES) => {
        const sessionId = String(response.session_id || "").trim();
        if (!sessionId) return;

        const sessions = get().sessions;
        const previous = sessions[sessionId]?.turns ?? [];
        const previousMap = new Map(previous.map((row) => [row.id, row]));
        const nextTurns = dedupeTurns(
          response.turns.map((turn) => toStoredTurn(turn, previousMap.get(buildMessageId(turn))))
        );

        const assistantIndex = (() => {
          for (let i = nextTurns.length - 1; i >= 0; i -= 1) {
            if (nextTurns[i].role === "assistant") return i;
          }
          return -1;
        })();

        if (assistantIndex >= 0) {
          const responseMessageId = String(response.message_id || "").trim();
          const targetIndex = responseMessageId
            ? nextTurns.findIndex((row) => row.id === responseMessageId)
            : assistantIndex;
          const next = nextTurns[targetIndex >= 0 ? targetIndex : assistantIndex];
          const messageId = responseMessageId || next.id;
          const writeIndex = targetIndex >= 0 ? targetIndex : assistantIndex;
          nextTurns[writeIndex] = {
            ...next,
            presentation: {
              messageId,
              mode: String(response.mode ?? ""),
              language: String(response.language ?? "en"),
              cards: Array.isArray(response.cards) ? response.cards : [],
              debug: response.debug && typeof response.debug === "object" ? response.debug : {},
              traceId: String(response.trace_id ?? ""),
              evidencePackId: String(response.evidence_pack_id ?? ""),
            },
          };
        }

        set({
          sessions: {
            ...sessions,
            [sessionId]: {
              updatedAt: new Date().toISOString(),
              turns: trimTurns(nextTurns, maxMessages),
            },
          },
        });
      },

      hydrateSessionTurns: (sessionId: string, turns: ChatTurn[], maxMessages = MAX_PERSISTED_MESSAGES) => {
        const id = String(sessionId || "").trim();
        if (!id) return;
        const sessions = get().sessions;
        const previous = sessions[id]?.turns ?? [];
        const previousMap = new Map(previous.map((row) => [row.id, row]));
        const incoming = turns.map((turn) => toStoredTurn(turn, previousMap.get(buildMessageId(turn))));
        const merged = (() => {
          if (incoming.length === 0) {
            // Keep locally persisted conversation when API temporarily returns no turns.
            return previous;
          }
          const map = new Map<string, StoredChatMessage>();
          const incomingIds = new Set<string>();

          for (const row of previous) {
            map.set(row.id, row);
          }
          for (const row of incoming) {
            incomingIds.add(row.id);
            const prevRow = map.get(row.id);
            map.set(row.id, {
              ...row,
              presentation: row.presentation ?? prevRow?.presentation,
            });
          }

          const orderedIds = [
            ...incoming.map((row) => row.id),
            ...previous.map((row) => row.id).filter((rowId) => !incomingIds.has(rowId)),
          ];
          return dedupeTurns(
            orderedIds
              .map((rowId) => map.get(rowId))
              .filter((row): row is StoredChatMessage => Boolean(row))
          );
        })();
        set({
          sessions: {
            ...sessions,
            [id]: {
              updatedAt: new Date().toISOString(),
              turns: trimTurns(merged, maxMessages),
            },
          },
        });
      },

      clearSession: (sessionId: string) => {
        const id = String(sessionId || "").trim();
        if (!id) return;
        const sessions = { ...get().sessions };
        delete sessions[id];
        set({ sessions });
      },
    }),
    {
      name: "of-chat-session-store",
      storage: createJSONStorage(() => localStorage),
      partialize: (state) => ({ sessions: state.sessions }),
    }
  )
);
