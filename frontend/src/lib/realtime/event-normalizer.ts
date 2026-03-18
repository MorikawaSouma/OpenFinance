import type { SseEvent } from "@/lib/types";

export type NormalizedEventDomain =
  | "task"
  | "chat"
  | "risk"
  | "approval"
  | "artifact"
  | "audit"
  | "reasoning"
  | "unknown";

export type NormalizedSseEvent = {
  domain: NormalizedEventDomain;
  event: SseEvent;
  shouldTouchTasks: boolean;
  shouldTouchChatWorkspace: boolean;
  shouldTouchRiskApproval: boolean;
  shouldTouchCatalogSummary: boolean;
};

const TASK_EVENT_TYPES = new Set(["task.created", "task.progress", "task.heartbeat", "task.done", "task.error"]);
const CHAT_EVENT_TYPES = new Set(["chat.done"]);
const RISK_EVENT_TYPES = new Set(["risk.event"]);
const APPROVAL_EVENT_TYPES = new Set(["approval.status_changed"]);
const ARTIFACT_EVENT_TYPES = new Set(["report.ready", "artifact.created", "artifact.updated"]);
const REASONING_EVENT_TYPES = new Set(["reasoning.step.created", "reasoning.step.updated", "reasoning.trace.final"]);

export function classifySseEvent(event: SseEvent): NormalizedSseEvent {
  const type = String(event.type ?? "").trim().toLowerCase();

  if (TASK_EVENT_TYPES.has(type)) {
    return {
      domain: "task",
      event,
      shouldTouchTasks: true,
      shouldTouchChatWorkspace: type === "task.done" || type === "task.error",
      shouldTouchRiskApproval: false,
      shouldTouchCatalogSummary: type === "task.done",
    };
  }

  if (CHAT_EVENT_TYPES.has(type)) {
    return {
      domain: "chat",
      event,
      shouldTouchTasks: false,
      shouldTouchChatWorkspace: true,
      shouldTouchRiskApproval: false,
      shouldTouchCatalogSummary: false,
    };
  }

  if (RISK_EVENT_TYPES.has(type)) {
    return {
      domain: "risk",
      event,
      shouldTouchTasks: false,
      shouldTouchChatWorkspace: false,
      shouldTouchRiskApproval: true,
      shouldTouchCatalogSummary: false,
    };
  }

  if (APPROVAL_EVENT_TYPES.has(type)) {
    return {
      domain: "approval",
      event,
      shouldTouchTasks: false,
      shouldTouchChatWorkspace: false,
      shouldTouchRiskApproval: true,
      shouldTouchCatalogSummary: false,
    };
  }

  if (ARTIFACT_EVENT_TYPES.has(type)) {
    return {
      domain: "artifact",
      event,
      shouldTouchTasks: false,
      shouldTouchChatWorkspace: false,
      shouldTouchRiskApproval: false,
      shouldTouchCatalogSummary: true,
    };
  }

  if (REASONING_EVENT_TYPES.has(type)) {
    return {
      domain: "reasoning",
      event,
      shouldTouchTasks: false,
      shouldTouchChatWorkspace: true,
      shouldTouchRiskApproval: false,
      shouldTouchCatalogSummary: false,
    };
  }

  if (type.startsWith("audit.")) {
    return {
      domain: "audit",
      event,
      shouldTouchTasks: false,
      shouldTouchChatWorkspace: true,
      shouldTouchRiskApproval: false,
      shouldTouchCatalogSummary: false,
    };
  }

  return {
    domain: "unknown",
    event,
    shouldTouchTasks: false,
    shouldTouchChatWorkspace: false,
    shouldTouchRiskApproval: false,
    shouldTouchCatalogSummary: false,
  };
}
