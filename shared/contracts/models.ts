export type EventType =
  | "chat.delta"
  | "chat.done"
  | "tool.call"
  | "tool.result"
  | "task.created"
  | "task.progress"
  | "task.heartbeat"
  | "task.variant_started"
  | "task.variant_done"
  | "task.done"
  | "task.error"
  | "agent.dispatched"
  | "agent.completed"
  | "tool.call.started"
  | "tool.call.finished"
  | "artifact.created"
  | "audit.tail"
  | "reasoning.step.created"
  | "reasoning.step.updated"
  | "reasoning.trace.final"
  | "report.ready"
  | "audit.trace";

export interface SseEvent {
  type: EventType;
  trace_id: string;
  session_id: string;
  timestamp: string;
  payload: Record<string, unknown>;
}
