// Historical phase-1 planning snapshot only.
// This file is not the current runtime truth after phase-2 ownership migration and WorkbenchProvider removal.
// Keep it only as migration archaeology until a later cleanup deletes or replaces it with a current architecture note.
export type RefreshOwner =
  | "legacy-workbench-provider"
  | "workbench-shell-provider"
  | "research-context-provider"
  | "task-realtime-provider"
  | "risk-approval-provider"
  | "catalog-summary-provider"
  | "chat-workspace-provider"
  | "pipeline-workspace-provider"
  | "realtime-coordinator-provider";

export type RefreshOwnerStatus = "legacy-active" | "placeholder" | "planned-group2";

export type RefreshPath =
  | "bootstrap:legacy-workbench"
  | "bootstrap:shell"
  | "bootstrap:research-context"
  | "sse:global-stream"
  | "polling:legacy-core-refresh"
  | "polling:task-fallback"
  | "polling:chat-fallback"
  | "manual:legacy-core-refresh"
  | "manual:task-domain-refresh"
  | "manual:risk-domain-refresh"
  | "manual:chat-domain-refresh"
  | "mutation:task-creation"
  | "mutation:risk-approval"
  | "mutation:restore-trace";

export const PHASE1_GROUP1_REFRESH_OWNERS: Record<
  RefreshPath,
  {
    owner: RefreshOwner;
    status: RefreshOwnerStatus;
    notes: string;
  }
> = {
  "bootstrap:legacy-workbench": {
    owner: "legacy-workbench-provider",
    status: "legacy-active",
    notes: "Group 1 keeps legacy bootstrap fetch behavior intact.",
  },
  "bootstrap:shell": {
    owner: "workbench-shell-provider",
    status: "placeholder",
    notes: "Only hydrates legacy mode from localStorage. It does not render toast UI yet.",
  },
  "bootstrap:research-context": {
    owner: "research-context-provider",
    status: "placeholder",
    notes: "Only rehydrates persisted IDs. It does not trigger route hydration yet.",
  },
  "sse:global-stream": {
    owner: "legacy-workbench-provider",
    status: "legacy-active",
    notes: "RealtimeCoordinatorProvider is mounted as a placeholder and intentionally does not subscribe yet.",
  },
  "polling:legacy-core-refresh": {
    owner: "legacy-workbench-provider",
    status: "legacy-active",
    notes: "The existing 30-second core refresh remains live in group 1.",
  },
  "polling:task-fallback": {
    owner: "task-realtime-provider",
    status: "planned-group2",
    notes: "Task-specific fallback polling will move here after consumer migration.",
  },
  "polling:chat-fallback": {
    owner: "chat-workspace-provider",
    status: "planned-group2",
    notes: "Chat fallback polling is deferred until the chat route is migrated.",
  },
  "manual:legacy-core-refresh": {
    owner: "legacy-workbench-provider",
    status: "legacy-active",
    notes: "Pages still call legacy refresh paths until their consumers are migrated.",
  },
  "manual:task-domain-refresh": {
    owner: "task-realtime-provider",
    status: "planned-group2",
    notes: "Tasks page refresh will move here with page consumer migration.",
  },
  "manual:risk-domain-refresh": {
    owner: "risk-approval-provider",
    status: "planned-group2",
    notes: "Risk and settings pages still rely on the legacy provider in group 1.",
  },
  "manual:chat-domain-refresh": {
    owner: "chat-workspace-provider",
    status: "planned-group2",
    notes: "Chat route refresh ownership is deferred with chat workspace migration.",
  },
  "mutation:task-creation": {
    owner: "legacy-workbench-provider",
    status: "legacy-active",
    notes: "Task-creating mutations remain on the old provider until group 2 replaces consumers.",
  },
  "mutation:risk-approval": {
    owner: "legacy-workbench-provider",
    status: "legacy-active",
    notes: "Risk and approval mutations remain legacy-owned in group 1.",
  },
  "mutation:restore-trace": {
    owner: "legacy-workbench-provider",
    status: "legacy-active",
    notes: "Restore flow stays unchanged until chat and reports consumers are migrated.",
  },
};
