"use client";

import { api } from "@/lib/api";
import { recordStateUpdate } from "@/lib/debug";
import type { ApprovalRequest, ChatResponse, RiskStatus, SseEvent, TaskRecord } from "@/lib/types";

function toObject(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : {};
}

export function extractTaskIdsFromChatResponse(response: ChatResponse): string[] {
  const debug = toObject(response.debug);
  const direct = [
    String(debug.task_id ?? "").trim(),
    String(debug.parent_task_id ?? "").trim(),
    String(debug.us_parent_task_id ?? "").trim(),
    String(debug.jp_parent_task_id ?? "").trim(),
  ].filter((row) => row.length > 0);

  const childTaskIdsRaw = debug.child_task_ids;
  const childTaskIds = Array.isArray(childTaskIdsRaw)
    ? childTaskIdsRaw.map((row) => String(row ?? "").trim()).filter((row) => row.length > 0)
    : [];
  return Array.from(new Set([...direct, ...childTaskIds]));
}

export function mergeChatRiskSnapshot(previous: RiskStatus | null, snapshot: Record<string, unknown>): RiskStatus {
  return {
    ...(previous ?? {
      mode: "paper",
      kill_switch_enabled: false,
      live_trading_enabled: false,
      paper_trading_enabled: false,
      risk_max_order_qty: 0,
    }),
    live_trading_enabled: Boolean(snapshot.live_trading_enabled),
    paper_trading_enabled: Boolean(snapshot.paper_trading_enabled),
    kill_switch_enabled: Boolean(snapshot.kill_switch),
    live_approval_state: String(snapshot.live_lock_status ?? previous?.live_approval_state ?? "locked"),
    current_drawdown: Number(snapshot.drawdown ?? previous?.current_drawdown ?? 0),
    current_volatility: Number(snapshot.volatility ?? previous?.current_volatility ?? 0),
    risk_status: String(snapshot.risk_level ?? previous?.risk_status ?? "normal"),
    max_account_drawdown_limit: Number(
      toObject(snapshot.limits).max_account_drawdown_limit ?? previous?.max_account_drawdown_limit ?? 0
    ),
    abnormal_volatility_limit: Number(
      toObject(snapshot.limits).abnormal_volatility_limit ?? previous?.abnormal_volatility_limit ?? 0
    ),
    risk_max_order_qty: Number(toObject(snapshot.limits).risk_max_order_qty ?? previous?.risk_max_order_qty ?? 0),
    updated_at: String(snapshot.updated_at ?? ""),
  };
}

export function mapChatApprovalSnapshot(snapshot: Record<string, unknown>): ApprovalRequest[] {
  const approvalsRaw = snapshot.items;
  if (!Array.isArray(approvalsRaw)) return [];
  return approvalsRaw
    .map((row) => toObject(row))
    .map((row) => ({
      request_id: String(row.request_id ?? ""),
      target: String(row.target ?? ""),
      action: "request_trade_enable",
      status: String(row.status ?? "pending") as ApprovalRequest["status"],
      context: {
        use_case: String(row.use_case ?? ""),
        plan_id: String(row.plan_id ?? ""),
      },
      created_at: String(row.created_at ?? ""),
      updated_at: String(row.created_at ?? ""),
      expires_at: null,
      transitions: [],
    }))
    .filter((row) => row.request_id.length > 0);
}

export function buildReasoningEventsFromChatResponse(response: ChatResponse): SseEvent[] {
  const debug = toObject(response.debug);
  const debugReasoningSteps = debug.reasoning_steps;
  if (!Array.isArray(debugReasoningSteps)) return [];

  const events: SseEvent[] = [];
  for (let i = 0; i < debugReasoningSteps.length; i += 1) {
    const step = toObject(debugReasoningSteps[i]);
    const createdAt = String(step.created_at ?? new Date().toISOString());
    events.push({
      event_id: `chatresp:${response.message_id}:reasoning:${i}`,
      type: "reasoning.step.created",
      trace_id: String(response.trace_id ?? ""),
      session_id: String(response.session_id ?? ""),
      timestamp: createdAt,
      payload: {
        step,
        agent_name: String(step.agent_name ?? ""),
        step_idx: Number(step.step_idx ?? i + 1),
        step_type: String(step.step_type ?? "warning"),
        title: String(step.title ?? ""),
        summary: String(step.summary ?? ""),
        evidence_refs: Array.isArray(step.evidence_refs) ? step.evidence_refs : [],
        parse_error: String(step.parse_error ?? ""),
        prompt_hash: String(step.prompt_hash ?? ""),
      },
    });
  }

  events.push({
    event_id: `chatresp:${response.message_id}:reasoning:final`,
    type: "reasoning.trace.final",
    trace_id: String(response.trace_id ?? ""),
    session_id: String(response.session_id ?? ""),
    timestamp: new Date().toISOString(),
    payload: {
      agent_name: "GeneralInfo",
      steps_count: debugReasoningSteps.length,
      steps: debugReasoningSteps,
      has_parse_error: debugReasoningSteps.some((row) => Boolean(toObject(row).parse_error)),
    },
  });
  return events;
}

type ExecuteChatSendOptions = {
  message: string;
  sessionIdForRequest: string | null;
  includeDebug: boolean;
  currentRiskSnapshot: RiskStatus | null;
  commitResolvedSessionScope: (sessionId: string | null) => void;
  upsertChatResponse: (response: ChatResponse, maxMessages?: number) => void;
  setRiskSnapshot: (snapshot: RiskStatus | null, refreshedAt?: string | null) => void;
  upsertApproval: (row: ApprovalRequest, refreshedAt?: string | null) => void;
  prependEvents: (rows: SseEvent[]) => void;
  addActiveTask: (sessionId: string, taskId: string) => void;
  upsertTask: (task: TaskRecord) => void;
  syncTaskTerminalState: (sessionId: string, taskId: string, status: string) => void;
};

export async function executeChatSend(options: ExecuteChatSendOptions): Promise<ChatResponse> {
  const response = await api.sendChat({
    message: options.message,
    session_id: options.sessionIdForRequest,
    include_debug: options.includeDebug,
  });

  options.upsertChatResponse(response);
  recordStateUpdate("chatTurns");

  const reasoningEvents = buildReasoningEventsFromChatResponse(response);
  if (reasoningEvents.length > 0) {
    options.prependEvents([...reasoningEvents].reverse());
    recordStateUpdate("events");
  }

  const riskSnapshot = toObject(response.risk_snapshot);
  if (Object.keys(riskSnapshot).length > 0) {
    options.setRiskSnapshot(mergeChatRiskSnapshot(options.currentRiskSnapshot, riskSnapshot));
    recordStateUpdate("risk");
  }

  const mappedApprovals = mapChatApprovalSnapshot(toObject(response.approvals_snapshot));
  if (mappedApprovals.length > 0) {
    for (const row of mappedApprovals) {
      options.upsertApproval(row);
    }
    recordStateUpdate("approvals");
  }

  options.commitResolvedSessionScope(String(response.session_id ?? "").trim() || null);

  const linkedTaskIds = extractTaskIdsFromChatResponse(response);
  if (linkedTaskIds.length > 0) {
    for (const taskId of linkedTaskIds) {
      options.addActiveTask(response.session_id, taskId);
      try {
        const row = await api.getTask(taskId);
        options.upsertTask(row);
        options.syncTaskTerminalState(response.session_id, taskId, row.status);
      } catch {
        // Task may not be queryable immediately; SSE or later targeted fetch can backfill it.
      }
    }
    recordStateUpdate("tasks");
  }

  return response;
}
