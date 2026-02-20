export type EventType =
  | "chat.delta"
  | "chat.done"
  | "tool.call"
  | "tool.result"
  | "task.created"
  | "task.progress"
  | "task.done"
  | "report.ready"
  | "audit.trace";

export interface SseEvent {
  type: EventType;
  trace_id: string;
  session_id: string;
  timestamp: string;
  payload: Record<string, unknown>;
}
