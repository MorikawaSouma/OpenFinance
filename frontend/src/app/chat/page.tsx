
"use client";

import Link from "next/link";
import { FormEvent, useCallback, useEffect, useMemo, useRef, useState, type MutableRefObject } from "react";
import { Code2, FileText } from "lucide-react";

import { EmptyState } from "@/components/common/empty-state";
import { useWorkbench } from "@/components/providers/workbench-provider";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TBody, Td, THead, Th, Tr } from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { buildMessageId, useChatSessionStore, type StoredChatMessage } from "@/lib/chat-session-store";
import {
  recordComponentMount,
  recordComponentUnmount,
  recordRender,
  resetDebugSnapshot,
  useDebugSnapshot,
} from "@/lib/debug";
import { messages } from "@/lib/messages";
import type { ChatResponse, ChatTurn, TaskRecord } from "@/lib/types";

type EnrichedTurn = StoredChatMessage;

const CHAT_BOTTOM_THRESHOLD_PX = 120;
const EMPTY_STORED_TURNS: EnrichedTurn[] = [];
const CARD_PRIORITY: Record<string, number> = {
  summary: 0,
  metrics: 1,
  comparison_table: 1,
  confidence: 2,
  key_differences: 2,
  diff: 2,
  drivers: 3,
  risks: 3,
  watch: 3,
  evidence: 4,
  next_steps: 5,
};

function useMountLogger(componentName: string) {
  useEffect(() => {
    recordComponentMount(componentName);
    console.info(`[debug] ${componentName} mounted`);
    return () => {
      recordComponentUnmount(componentName);
      console.info(`[debug] ${componentName} unmounted`);
    };
  }, [componentName]);
}

function useRenderMetric(componentName: string) {
  const startedAt = typeof performance !== "undefined" ? performance.now() : Date.now();
  useEffect(() => {
    const endedAt = typeof performance !== "undefined" ? performance.now() : Date.now();
    recordRender(componentName, endedAt - startedAt);
  });
}

function userSafeText(text: string) {
  return text
    .split("\n")
    .filter((line) => !/\[glm|Agent summary:|Agent consensus:|EvidencePack:|trace_id|artifact_id|raw/i.test(line))
    .join("\n")
    .trim();
}

function normalizeCardItems(items: Array<Record<string, unknown> | string> | undefined) {
  return Array.isArray(items) ? items : [];
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : {};
}

function toFallbackTurns(turns: ChatTurn[]): EnrichedTurn[] {
  return turns.map((turn) => ({
    ...turn,
    id: buildMessageId(turn),
  }));
}

function cardFingerprint(card: ChatResponse["cards"][number]) {
  const base = {
    type: card.type,
    title: card.title,
    content: card.content ?? "",
    subtitle: card.subtitle ?? "",
    metrics: card.metrics ?? [],
    items: card.items ?? [],
    table: card.table ?? [],
    actions: card.actions ?? [],
  };
  return JSON.stringify(base);
}

function normalizeCards(cards: ChatResponse["cards"]) {
  const rows = Array.isArray(cards) ? cards : [];
  const seen = new Set<string>();
  const deduped: Array<ChatResponse["cards"][number] & { __order: number; __cardId: string }> = [];
  for (let i = 0; i < rows.length; i += 1) {
    const row = rows[i];
    const cardId = String(row.card_id ?? `${row.type}:${i}`);
    const fingerprint = `${cardId}|${cardFingerprint(row)}`;
    if (seen.has(fingerprint)) continue;
    seen.add(fingerprint);
    deduped.push({ ...row, __order: i, __cardId: cardId });
  }
  deduped.sort((a, b) => {
    const pa = CARD_PRIORITY[a.type] ?? 99;
    const pb = CARD_PRIORITY[b.type] ?? 99;
    if (pa !== pb) return pa - pb;
    return a.__order - b.__order;
  });
  return deduped.map(({ __order: _order, __cardId: _cardId, ...card }) => card);
}

function isRobustnessPrompt(message: string) {
  const low = message.toLowerCase();
  return /稳健性|鲁棒|成本翻倍|参数扰动/.test(message) || /robustness|stress|cost x|cost multipliers?|perturb/.test(low);
}

function stageLabel(stage: string, language: string) {
  const key = String(stage || "").trim().toLowerCase();
  const zh = language === "zh";
  const map: Record<string, string> = {
    "pipeline.start": zh ? "初始化任务" : "Initializing task",
    "plan.compose": zh ? "生成研究计划" : "Composing plan",
    "agent.reasoning": zh ? "多专家推理" : "Agent reasoning",
    "evidence.pack": zh ? "整理证据" : "Packing evidence",
    "dataset.prepare": zh ? "准备数据集" : "Preparing dataset",
    "variant.factor": zh ? "计算因子" : "Computing factor",
    "variant.strategy": zh ? "选择策略" : "Selecting strategy",
    "variant.backtest": zh ? "运行回测" : "Running backtest",
    "variants.running": zh ? "批量实验中" : "Running variants",
    "backtest.compare": zh ? "汇总对比" : "Comparing backtests",
    "paper.trade": zh ? "纸交易演练" : "Paper trading",
    "pipeline.done": zh ? "完成汇总" : "Finalizing results",
  };
  return map[key] ?? (zh ? "处理中" : "Running");
}

function elapsedLabel(ms: number, language: string) {
  const secs = Math.max(0, Math.floor(ms / 1000));
  if (secs <= 0) return "";
  return language === "zh" ? `${secs}秒` : `${secs}s`;
}

type ReasoningEvidenceRow = {
  source_id: string;
  title: string;
  ts: string;
};

type ReasoningStepRow = {
  event_id: string;
  trace_id: string;
  session_id: string;
  timestamp: string;
  agent_name: string;
  step_idx: number;
  step_type: string;
  title: string;
  summary: string;
  evidence_refs: ReasoningEvidenceRow[];
  parse_error: string;
  prompt_hash: string;
  raw: Record<string, unknown>;
};

function normalizeReasoningEvidenceRows(value: unknown): ReasoningEvidenceRow[] {
  if (!Array.isArray(value)) return [];
  const rows: ReasoningEvidenceRow[] = [];
  for (const item of value) {
    const row = asRecord(item);
    const sourceId = String(row.source_id ?? "").trim();
    if (!sourceId) continue;
    rows.push({
      source_id: sourceId,
      title: String(row.title ?? "").trim(),
      ts: String(row.ts ?? "").trim(),
    });
  }
  return rows;
}

function toReasoningStepRow(event: { event_id?: string; trace_id: string; session_id: string; timestamp: string; payload: Record<string, unknown> }) {
  const payload = asRecord(event.payload);
  const stepPayload = asRecord(payload.step);
  const row = Object.keys(stepPayload).length > 0 ? stepPayload : payload;
  const stepIdx = Number(row.step_idx ?? payload.step_idx ?? 0);
  if (!Number.isFinite(stepIdx) || stepIdx <= 0) return null;
  return {
    event_id: String(event.event_id ?? ""),
    trace_id: String(row.trace_id ?? event.trace_id ?? ""),
    session_id: String(row.session_id ?? event.session_id ?? ""),
    timestamp: String(row.created_at ?? event.timestamp ?? ""),
    agent_name: String(row.agent_name ?? payload.agent_name ?? "agent"),
    step_idx: stepIdx,
    step_type: String(row.step_type ?? payload.step_type ?? "warning"),
    title: String(row.title ?? payload.title ?? ""),
    summary: String(row.summary ?? payload.summary ?? ""),
    evidence_refs: normalizeReasoningEvidenceRows(row.evidence_refs ?? payload.evidence_refs),
    parse_error: String(row.parse_error ?? payload.parse_error ?? ""),
    prompt_hash: String(row.prompt_hash ?? payload.prompt_hash ?? ""),
    raw: row,
  } satisfies ReasoningStepRow;
}

function DebugPanel({
  virtualizerDebugRef,
  atBottomRef,
  autoScrollEnabledRef,
  sseConnectionState,
}: {
  virtualizerDebugRef: MutableRefObject<{
    measureCount: number;
    scrollToIndexCalls: number;
  }>;
  atBottomRef: MutableRefObject<boolean>;
  autoScrollEnabledRef: MutableRefObject<boolean>;
  sseConnectionState: "connecting" | "open" | "closed" | "error" | "reconnecting";
}) {
  const [virtualizerStats, setVirtualizerStats] = useState(() => ({
    measureCount: virtualizerDebugRef.current.measureCount,
    scrollToIndexCalls: virtualizerDebugRef.current.scrollToIndexCalls,
    isAtBottom: atBottomRef.current,
    isAutoScrollEnabled: autoScrollEnabledRef.current,
  }));
  const snapshot = useDebugSnapshot();
  const fullReload = snapshot.navigationType === "reload";

  useEffect(() => {
    const sync = () => {
      setVirtualizerStats((prev) => {
        const next = {
          measureCount: virtualizerDebugRef.current.measureCount,
          scrollToIndexCalls: virtualizerDebugRef.current.scrollToIndexCalls,
          isAtBottom: atBottomRef.current,
          isAutoScrollEnabled: autoScrollEnabledRef.current,
        };
        if (
          prev.measureCount === next.measureCount &&
          prev.scrollToIndexCalls === next.scrollToIndexCalls &&
          prev.isAtBottom === next.isAtBottom &&
          prev.isAutoScrollEnabled === next.isAutoScrollEnabled
        ) {
          return prev;
        }
        return next;
      });
    };
    sync();
    const timer = window.setInterval(sync, 400);
    return () => {
      window.clearInterval(timer);
    };
  }, [atBottomRef, autoScrollEnabledRef, virtualizerDebugRef]);

  return (
    <Card className="mt-3 border-dashed">
      <CardHeader className="pb-2">
        <CardTitle className="text-sm">{messages.chat.debugPanelTitle}</CardTitle>
        <CardDescription>{messages.chat.debugPanelDesc}</CardDescription>
      </CardHeader>
      <CardContent className="grid gap-2 text-xs text-muted-foreground md:grid-cols-2">
        <p>{messages.chat.navigationType}: <span className="text-foreground">{snapshot.navigationType}</span></p>
        <p>{messages.chat.fullReload}: <span className="text-foreground">{fullReload ? messages.chat.yes : messages.chat.no}</span></p>
        <p className="md:col-span-2">{messages.chat.lastRouteChange}: <span className="text-foreground">{snapshot.lastRouteChangeAt ?? "-"}</span></p>
        <p>{messages.chat.sseOpen}: <span className="text-foreground">{snapshot.sse.openCount}</span></p>
        <p>{messages.chat.sseClose}: <span className="text-foreground">{snapshot.sse.closeCount}</span></p>
        <p>{messages.chat.sseError}: <span className="text-foreground">{snapshot.sse.errorCount}</span></p>
        <p>{messages.chat.sseReconnects}: <span className="text-foreground">{snapshot.sse.reconnectCount}</span></p>
        <p>SSE State: <span className="text-foreground">{sseConnectionState}</span></p>
        <p>{messages.chat.renderCount}: <span className="text-foreground">ChatPage {snapshot.renderCount.ChatPage ?? 0}</span></p>
        <p>{messages.chat.avgRenderMs}: <span className="text-foreground">ChatPage {snapshot.avgRenderMs.ChatPage ?? 0}</span></p>
        <p>{messages.chat.mounts}: <span className="text-foreground">ChatPage {snapshot.componentMounts.ChatPage ?? 0}</span></p>
        <p>{messages.chat.unmounts}: <span className="text-foreground">ChatPage {snapshot.componentUnmounts.ChatPage ?? 0}</span></p>
        <p>{messages.chat.virtualizerMeasureCount}: <span className="text-foreground">{virtualizerStats.measureCount}</span></p>
        <p>{messages.chat.scrollToIndexCalls}: <span className="text-foreground">{virtualizerStats.scrollToIndexCalls}</span></p>
        <p>{messages.chat.atBottom}: <span className="text-foreground">{virtualizerStats.isAtBottom ? messages.chat.yes : messages.chat.no}</span></p>
        <p>{messages.chat.autoScrollEnabled}: <span className="text-foreground">{virtualizerStats.isAutoScrollEnabled ? messages.chat.yes : messages.chat.no}</span></p>
        <p className="md:col-span-2">{messages.chat.stateUpdates}: <span className="text-foreground">{JSON.stringify(snapshot.stateUpdateCount)}</span></p>
        <div className="md:col-span-2">
          <Button size="sm" variant="outline" onClick={() => resetDebugSnapshot()}>
            {messages.chat.resetDebug}
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

function TurnCard({
  turn,
  mode,
  onAction,
  taskById,
  onRequestRemeasure,
}: {
  turn: EnrichedTurn;
  mode: "user" | "developer";
  onAction: (action: string, payload?: Record<string, unknown>) => void;
  taskById: Map<string, TaskRecord>;
  onRequestRemeasure?: () => void;
}) {
  const isUser = turn.role === "user";
  const answerText = mode === "developer" || isUser ? turn.content : userSafeText(turn.content);
  const presentation = turn.presentation;
  const cards = normalizeCards(presentation?.cards ?? []);
  const language = presentation?.language ?? "en";
  const isPendingAssistant = !isUser && turn.id.startsWith("pending:");
  const isZh = language === "zh";
  const llmNotice =
    mode === "developer" && presentation?.debug && typeof presentation.debug.general_info_llm_notice === "string"
      ? String(presentation.debug.general_info_llm_notice)
      : "";
  const evidenceFallback = language === "zh" ? "暂无可引用证据，可尝试刷新证据。" : "No citable evidence yet. Try refreshing evidence.";
  const debug = asRecord(presentation?.debug);
  const trackedTaskId = String(
    debug.parent_task_id ?? debug.task_id ?? debug.us_parent_task_id ?? debug.jp_parent_task_id ?? ""
  ).trim();
  const trackedTask = trackedTaskId ? taskById.get(trackedTaskId) : undefined;
  const trackedMeta = asRecord(trackedTask?.meta);
  const trackedStage = String(trackedMeta.last_stage ?? "").trim();
  const trackedElapsedMs = Number(trackedMeta.last_elapsed_ms ?? 0);
  const trackedStatusText = String(trackedMeta.status_text ?? "").trim();
  const taskResultRef = asRecord(trackedTask?.result_ref);
  const taskRunId = String(taskResultRef.run_id ?? "").trim();
  const taskOpenPath = (() => {
    const openPath = String(taskResultRef.open_path ?? "").trim();
    if (openPath) return openPath;
    if (taskRunId) return `/reports/${taskRunId}`;
    return "";
  })();
  const taskBadge = trackedTask ? `${String(trackedTask.status || "running")} · ${Math.max(0, Math.min(100, Number(trackedTask.progress || 0)))}%` : "";
  const taskStageLabel = trackedTask ? stageLabel(trackedStage, language) : "";
  const taskElapsedText = trackedTask ? elapsedLabel(trackedElapsedMs, language) : "";

  const renderCard = (card: ChatResponse["cards"][number], index: number) => {
    const cardKey = String(card.card_id ?? `card-${index}-${card.type}`);
    if (card.type === "summary" || card.type === "risks" || card.type === "drivers" || card.type === "watch") {
      if (isPendingAssistant && card.type === "summary") {
        return (
          <div key={cardKey} className="min-h-[92px] rounded-md border bg-background p-3">
            <p className="text-xs font-semibold">{card.title}</p>
            <div className="mt-2 space-y-2">
              <Skeleton className="h-3 w-10/12" />
              <Skeleton className="h-3 w-8/12" />
              <Skeleton className="h-3 w-6/12" />
            </div>
          </div>
        );
      }
      return (
        <div key={cardKey} className="rounded-md border bg-background p-3">
          <p className="text-xs font-semibold">{card.title}</p>
          {card.content ? <p className="mt-1 whitespace-pre-wrap text-sm">{card.content}</p> : null}
          {card.subtitle ? <p className="mt-1 whitespace-pre-wrap text-xs text-muted-foreground">{card.subtitle}</p> : null}
          {trackedTask ? (
            <div className="mt-2 rounded border bg-muted/20 p-2">
              <p className="text-[11px] text-muted-foreground">
                {`Task #${trackedTask.task_id.replace(/-/g, "").slice(0, 8)} · ${taskBadge}`}
              </p>
              <p className="mt-1 text-[11px] text-muted-foreground">
                {language === "zh" ? "正在：" : "Stage: "}
                {taskStageLabel}
                {taskElapsedText ? ` (${taskElapsedText})` : ""}
                {trackedStatusText ? ` · ${trackedStatusText}` : ""}
              </p>
              <div className="mt-1 h-1.5 w-full rounded bg-muted/40">
                <div
                  className="h-1.5 rounded bg-primary transition-all"
                  style={{ width: `${Math.max(0, Math.min(100, Number(trackedTask.progress || 0)))}%` }}
                />
              </div>
              {trackedTask.error ? <p className="mt-1 text-[11px] text-destructive">{String(trackedTask.error)}</p> : null}
              {taskOpenPath ? (
                <div className="mt-2">
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => onAction("open_result", { path: taskOpenPath, task_id: trackedTask.task_id })}
                  >
                    {isZh ? "打开结果" : "Open Result"}
                  </Button>
                </div>
              ) : null}
            </div>
          ) : null}
        </div>
      );
    }
    if (card.type === "metrics") {
      const metrics = Array.isArray(card.metrics) ? card.metrics : [];
      return (
        <div key={cardKey} className="rounded-md border bg-background p-3">
          <p className="text-xs font-semibold">{card.title}</p>
          <div className="mt-2 grid gap-2 sm:grid-cols-2">
            {metrics.map((row, i) => (
              <div key={`metric-${i}`} className="rounded border bg-muted/20 p-2">
                <p className="text-[11px] text-muted-foreground">{row.name}</p>
                <p className="text-base font-semibold">{String(row.value ?? "-")}</p>
              </div>
            ))}
          </div>
        </div>
      );
    }
    if (card.type === "evidence") {
      const evidenceItems = normalizeCardItems(card.items);
      const groupedEvidence = evidenceItems.every(
        (row) => typeof row !== "string" && typeof row.market === "string" && Array.isArray(row.evidence)
      );
      return (
        <div key={cardKey} className="rounded-md border bg-background p-3">
          <p className="text-xs font-semibold">{card.title}</p>
          {groupedEvidence ? (
            <Tabs defaultValue={String((evidenceItems[0] as Record<string, unknown>).market || "US")} className="mt-2">
              <TabsList>
                {evidenceItems.map((row, i) => (
                  <TabsTrigger key={`ev-tab-${i}`} value={String((row as Record<string, unknown>).market || `m${i}`)}>
                    {String((row as Record<string, unknown>).market || `M${i + 1}`)}
                  </TabsTrigger>
                ))}
              </TabsList>
              {evidenceItems.map((row, i) => {
                const market = String((row as Record<string, unknown>).market || `M${i + 1}`);
                const marketRows = Array.isArray((row as Record<string, unknown>).evidence)
                  ? ((row as Record<string, unknown>).evidence as Array<Record<string, unknown>>)
                  : [];
                  return (
                    <TabsContent key={`ev-content-${i}`} value={market}>
                      <div className="max-h-72 space-y-2 overflow-y-auto pr-1">
                        {marketRows.slice(0, 4).map((item, j) => (
                          <details
                            key={`ev-${market}-${j}`}
                            className="rounded border bg-muted/20 p-2 text-xs"
                            onToggle={() => onRequestRemeasure?.()}
                          >
                            <summary className="cursor-pointer">
                              {`${String(item.title ?? (isZh ? "未命名来源" : "untitled"))} · ${String(item.source ?? "source")} · ${String(item.ts ?? "n/a")}`}
                            </summary>
                          <p className="mt-1 whitespace-pre-wrap text-muted-foreground">{String(item.snippet ?? "-")}</p>
                        </details>
                      ))}
                    </div>
                  </TabsContent>
                );
              })}
            </Tabs>
          ) : (
            <div className="mt-2 max-h-72 space-y-2 overflow-y-auto pr-1">
              {evidenceItems.length === 0 ? (
                <div className="rounded border bg-muted/20 px-2 py-1 text-xs text-muted-foreground">{evidenceFallback}</div>
              ) : (
                evidenceItems.slice(0, 3).map((row, i) => {
                  if (typeof row === "string") {
                    return (
                      <div key={`evidence-${i}`} className="rounded border bg-muted/20 p-2 text-xs">
                        {row}
                      </div>
                    );
                  }
                  const title = String(row.title ?? "untitled");
                  const source = String(row.source ?? (isZh ? "来源" : "source"));
                  const ts = String(row.ts ?? "n/a");
                  const snippet = String(row.snippet ?? "-");
                  return (
                    <details key={`evidence-${i}`} className="rounded border bg-muted/20 p-2 text-xs" onToggle={() => onRequestRemeasure?.()}>
                      <summary className="cursor-pointer">{`${title || (isZh ? "未命名来源" : "untitled")} · ${source} · ${ts}`}</summary>
                      <p className="mt-1 whitespace-pre-wrap text-muted-foreground">{snippet}</p>
                    </details>
                  );
                })
              )}
            </div>
          )}
        </div>
      );
    }
    if (card.type === "comparison_table") {
      const tableRows = Array.isArray(card.table) ? card.table : [];
      return (
        <div key={cardKey} className="rounded-md border bg-background p-3">
          <p className="text-xs font-semibold">{card.title}</p>
          {tableRows.length > 0 ? (
            <div className="mt-2 max-h-80 overflow-auto">
              <Table>
                <THead>
                  <Tr>
                    <Th>{isZh ? "指标" : "Metric"}</Th>
                    <Th>US</Th>
                    <Th>JP</Th>
                    <Th>{isZh ? "差异" : "Difference"}</Th>
                  </Tr>
                </THead>
                <TBody>
                  {tableRows.map((row, i) => (
                    <Tr key={`cmp-${i}`}>
                      <Td className="font-semibold">{String(row.metric ?? "-")}</Td>
                      <Td>{String(row.us ?? "-")}</Td>
                      <Td>{String(row.jp ?? "-")}</Td>
                      <Td>{String(row.difference ?? "-")}</Td>
                    </Tr>
                  ))}
                </TBody>
              </Table>
            </div>
          ) : null}
        </div>
      );
    }
    if (card.type === "key_differences") {
      const items = normalizeCardItems(card.items);
      return (
        <div key={cardKey} className="rounded-md border bg-background p-3">
          <p className="text-xs font-semibold">{card.title}</p>
          <div className="mt-2 space-y-1 text-sm">
            {items.map((row, i) => {
              if (typeof row === "string") {
                return <p key={`diff-${i}`}>- {row}</p>;
              }
              const text = String(row.text ?? row.point ?? "-");
              const cites = Array.isArray(row.citations) ? row.citations.map((x) => Number(x)).filter((x) => Number.isFinite(x)) : [];
              return (
                <p key={`diff-${i}`}>
                  - {text}
                  {cites.length > 0 ? <span className="ml-1 text-xs text-muted-foreground">[{cites.join("][")}]</span> : null}
                </p>
              );
            })}
          </div>
        </div>
      );
    }
    if (card.type === "confidence") {
      return (
        <div key={cardKey} className="rounded-md border bg-background p-3">
          <p className="text-xs font-semibold">{card.title}</p>
          {card.content ? <p className="mt-1 text-lg font-semibold">{card.content}</p> : null}
          {card.subtitle ? <p className="mt-1 whitespace-pre-wrap text-xs text-muted-foreground">{card.subtitle}</p> : null}
        </div>
      );
    }
    if (card.type === "diff") {
      const tableRows = Array.isArray(card.table) ? card.table : [];
      return (
        <div key={cardKey} className="rounded-md border bg-background p-3">
          <p className="text-xs font-semibold">{card.title}</p>
          {card.content ? <p className="mt-1 whitespace-pre-wrap text-sm">{card.content}</p> : null}
          {tableRows.length > 0 ? (
            <div className="mt-2 overflow-x-auto rounded border">
              <table className="min-w-full text-xs">
                <thead className="bg-muted/30">
                  <tr>
                    <th className="px-2 py-1 text-left">{isZh ? "指标" : "Metric"}</th>
                    <th className="px-2 py-1 text-left">{isZh ? "调整前" : "Before"}</th>
                    <th className="px-2 py-1 text-left">{isZh ? "调整后" : "After"}</th>
                    <th className="px-2 py-1 text-left">{isZh ? "变化" : "Delta"}</th>
                  </tr>
                </thead>
                <tbody>
                  {tableRows.map((row, i) => (
                    <tr key={`diff-row-${i}`} className="border-t">
                      <td className="px-2 py-1 font-medium">{String(row.metric ?? "-")}</td>
                      <td className="px-2 py-1">{String(row.before ?? "-")}</td>
                      <td className="px-2 py-1">{String(row.after ?? "-")}</td>
                      <td className="px-2 py-1">{String(row.delta ?? "-")}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}
        </div>
      );
    }
    if (card.type === "next_steps") {
      const actions = Array.isArray(card.actions) ? card.actions : [];
      return (
        <div key={cardKey} className="rounded-md border bg-background p-3">
          <p className="text-xs font-semibold">{card.title}</p>
          <div className="mt-2 flex flex-wrap gap-2">
            {actions.map((row, i) => (
              <Button
                key={`action-${i}`}
                size="sm"
                variant={i === 0 ? "secondary" : "outline"}
                onClick={() => onAction(row.action, (row.payload ?? {}) as Record<string, unknown>)}
              >
                {row.label}
              </Button>
            ))}
          </div>
        </div>
      );
    }
    return (
      <div key={cardKey} className="rounded-md border bg-background p-3">
        <p className="text-xs font-semibold">{card.title}</p>
        {card.content ? <p className="mt-1 whitespace-pre-wrap text-sm">{card.content}</p> : null}
      </div>
    );
  };

  return (
    <div className={`max-w-[95%] rounded-lg p-3 text-sm ${isUser ? "ml-auto bg-primary text-primary-foreground" : "min-h-[72px] bg-muted/30"}`}>
      {isUser ? <p className="whitespace-pre-wrap">{answerText}</p> : null}

      {!isUser ? (
        <div className="space-y-2">
          {cards.length > 0 ? cards.map(renderCard) : <p className="whitespace-pre-wrap text-sm">{answerText}</p>}
          {llmNotice ? <div className="rounded-md border border-dashed bg-background p-2 text-xs text-muted-foreground">{llmNotice}</div> : null}
          {mode === "developer" ? (
            <details className="rounded-md border bg-background p-2">
              <summary className="cursor-pointer text-xs font-semibold">{messages.chat.rawPayload}</summary>
              <pre className="mt-1 overflow-x-auto text-[11px] text-muted-foreground">
                {JSON.stringify(
                  {
                    mode: presentation?.mode,
                    language: presentation?.language,
                    message_id: presentation?.messageId,
                    trace_id: presentation?.traceId,
                    evidence_pack_id: presentation?.evidencePackId,
                    parent_task_id:
                      (presentation?.debug?.parent_task_id as string | undefined) ??
                      (presentation?.debug?.us_parent_task_id as string | undefined) ??
                      (presentation?.debug?.jp_parent_task_id as string | undefined) ??
                      "",
                    debug: presentation?.debug ?? {},
                  },
                  null,
                  2
                )}
              </pre>
            </details>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
export default function ChatPage() {
  useMountLogger("ChatPage");
  useRenderMetric("ChatPage");
  useRenderMetric("SessionsList");
  useRenderMetric("TradingConsole");

  const {
    mode,
    chatSessions,
    chatTurns,
    activeSessionId,
    selectSession,
    sendChat,
    events,
    sseConnectionState,
    loadingCore,
    refreshingCore,
    tasks,
    pushToast,
    risk,
    approvals,
    setPaperRunning,
    requestApproval,
    approveApproval,
    enableApproval,
    revokeApproval,
  } = useWorkbench();

  const selectStoredTurns = useCallback(
    (state: { sessions: Record<string, { turns: EnrichedTurn[] }> }) => {
      if (!activeSessionId) return EMPTY_STORED_TURNS;
      return state.sessions[activeSessionId]?.turns ?? EMPTY_STORED_TURNS;
    },
    [activeSessionId]
  );
  const storedTurns = useChatSessionStore(selectStoredTurns);

  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [pendingMessage, setPendingMessage] = useState("");
  const [eventsOpen, setEventsOpen] = useState(false);
  const [traceFilter, setTraceFilter] = useState<"all" | "agent" | "tool" | "artifact" | "audit">("all");
  const [tracePanelTab, setTracePanelTab] = useState<"live_trace" | "reasoning_steps">("live_trace");
  const [restoredTraceId, setRestoredTraceId] = useState("");
  const [restoredSessionId, setRestoredSessionId] = useState("");
  const [restoreBannerShown, setRestoreBannerShown] = useState(false);
  const [unlockUseCase, setUnlockUseCase] = useState("");
  const [unlockPlanId, setUnlockPlanId] = useState("");
  const [unlockAck, setUnlockAck] = useState(false);

  const listRef = useRef<HTMLDivElement | null>(null);
  const atBottomRef = useRef(true);
  const autoScrollEnabledRef = useRef(true);
  const scrollListenerFrameRef = useRef<number | null>(null);
  const pendingScrollToLatestRafRef = useRef<number | null>(null);
  const pendingInitialScrollSessionRef = useRef<string | null>(null);
  const lastAssistantMarkerRef = useRef("");
  const virtualizerDebugRef = useRef({
    measureCount: 0,
    scrollToIndexCalls: 0,
  });

  useEffect(() => {
    recordComponentMount("SessionsList");
    console.info("[debug] SessionsList mounted");
    return () => {
      recordComponentUnmount("SessionsList");
      console.info("[debug] SessionsList unmounted");
    };
  }, []);

  useEffect(() => {
    recordComponentMount("TradingConsole");
    console.info("[debug] TradingConsole mounted");
    return () => {
      recordComponentUnmount("TradingConsole");
      console.info("[debug] TradingConsole unmounted");
    };
  }, []);

  const turns = useMemo<EnrichedTurn[]>(
    () => {
      const rows = storedTurns.length > 0 ? [...storedTurns] : toFallbackTurns(chatTurns);
      rows.sort((a, b) => {
        const at = Date.parse(String(a.created_at || ""));
        const bt = Date.parse(String(b.created_at || ""));
        if (Number.isFinite(at) && Number.isFinite(bt) && at !== bt) return at - bt;
        if (a.role !== b.role) return a.role === "user" ? -1 : 1;
        return String(a.id).localeCompare(String(b.id));
      });
      return rows;
    },
    [chatTurns, storedTurns]
  );
  const pendingAssistantTurn = useMemo<EnrichedTurn | null>(() => {
    if (!sending || !pendingMessage.trim()) return null;
    const isRobust = isRobustnessPrompt(pendingMessage);
    const language = /[\u4e00-\u9fff]/.test(pendingMessage) ? "zh" : "en";
    return {
      id: `pending:${activeSessionId ?? "default"}`,
      role: "assistant",
      content: isRobust
        ? language === "zh"
          ? "正在执行稳健性实验，请稍候…"
          : "Running robustness variants, please wait..."
        : language === "zh"
          ? "正在生成回答，请稍候…"
          : "Generating response, please wait...",
      created_at: new Date().toISOString(),
      presentation: {
        messageId: `pending:${activeSessionId ?? "default"}`,
        mode: "pending",
        language,
        cards: [
          {
            card_id: `pending:${activeSessionId ?? "default"}:summary:0`,
            type: "summary",
            title: language === "zh" ? "处理中" : "Running",
            content: isRobust
              ? language === "zh"
                ? "稳健性任务已提交，正在运行变体并收集指标。"
                : "Robustness task submitted. Running variants and collecting metrics."
              : language === "zh"
                ? "请求已提交，正在生成结构化卡片。"
                : "Request submitted. Generating structured cards.",
          },
          {
            card_id: `pending:${activeSessionId ?? "default"}:next_steps:1`,
            type: "next_steps",
            title: language === "zh" ? "你可以先查看" : "You can check",
            actions: [
              {
                label: language === "zh" ? "打开任务页" : "Open Tasks",
                action: "open_task",
                payload: {},
              },
            ],
          },
        ],
        debug: {},
        traceId: "",
        evidencePackId: "",
      },
    };
  }, [activeSessionId, pendingMessage, sending]);
  const renderTurns = useMemo(
    () => (pendingAssistantTurn ? [...turns, pendingAssistantTurn] : turns),
    [pendingAssistantTurn, turns]
  );
  const renderTurnRows = useMemo(() => {
    const seen = new Map<string, number>();
    return renderTurns.map((turn) => {
      const base = String(turn.id || `${turn.role}:${turn.created_at}`);
      const count = seen.get(base) ?? 0;
      seen.set(base, count + 1);
      const key = count === 0 ? base : `${base}:${count}`;
      return { key, turn };
    });
  }, [renderTurns]);
  const latestSession = useMemo(
    () => chatSessions.find((row) => row.session_id === activeSessionId) ?? chatSessions[0] ?? null,
    [activeSessionId, chatSessions]
  );
  const riskSnapshotTs = String(risk?.updated_at ?? "").trim();
  const taskById = useMemo(
    () => new Map(tasks.map((task) => [String(task.task_id), task])),
    [tasks]
  );
  const liveTraceEvents = useMemo(() => {
    const rows = events.slice(0, 160);
    if (traceFilter === "all") return rows;
    return rows.filter((ev) => {
      const type = String(ev.type || "").toLowerCase();
      if (traceFilter === "agent") return type.startsWith("agent.");
      if (traceFilter === "tool") return type.startsWith("tool.call");
      if (traceFilter === "artifact") return type.startsWith("artifact.");
      if (traceFilter === "audit") return type.startsWith("audit.");
      return true;
    });
  }, [events, traceFilter]);
  const reasoningStepEvents = useMemo(() => {
    const candidates = events.filter((ev) => {
      const type = String(ev.type || "").toLowerCase();
      return type === "reasoning.step.created" || type === "reasoning.step.updated";
    });
    const dedup = new Map<string, ReasoningStepRow>();
    for (const ev of candidates) {
      const mapped = toReasoningStepRow(ev);
      if (!mapped) continue;
      const key = `${mapped.trace_id}:${mapped.agent_name}:${mapped.step_idx}`;
      dedup.set(key, mapped);
    }
    return [...dedup.values()].sort((a, b) => {
      const agentCmp = a.agent_name.localeCompare(b.agent_name);
      if (agentCmp !== 0) return agentCmp;
      if (a.step_idx !== b.step_idx) return a.step_idx - b.step_idx;
      return a.timestamp.localeCompare(b.timestamp);
    });
  }, [events]);
  const reasoningTraceFinalEvents = useMemo(
    () => events.filter((ev) => String(ev.type || "").toLowerCase() === "reasoning.trace.final").slice(0, 32),
    [events]
  );

  const planOptions = useMemo(() => {
    const rows = new Set<string>();
    for (const session of chatSessions) {
      if (session.last_plan_id && session.last_plan_id.trim().length > 0) rows.add(session.last_plan_id);
    }
    return [...rows];
  }, [chatSessions]);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const params = new URLSearchParams(window.location.search);
    setRestoredTraceId((params.get("restored_trace_id") || "").trim());
    setRestoredSessionId((params.get("session_id") || "").trim());
  }, []);

  useEffect(() => {
    if (!restoredSessionId) return;
    if (activeSessionId === restoredSessionId) return;
    void selectSession(restoredSessionId).catch(() => undefined);
  }, [activeSessionId, restoredSessionId, selectSession]);

  useEffect(() => {
    if (!restoredTraceId || restoreBannerShown) return;
    pushToast("Context restored", `trace_id=${restoredTraceId}`, "success");
    setRestoreBannerShown(true);
  }, [pushToast, restoreBannerShown, restoredTraceId]);

  const updateBottomFlags = useCallback((nearBottom: boolean) => {
    atBottomRef.current = nearBottom;
    if (nearBottom && !autoScrollEnabledRef.current) {
      autoScrollEnabledRef.current = true;
    } else if (!nearBottom && autoScrollEnabledRef.current) {
      autoScrollEnabledRef.current = false;
    }
  }, []);

  const updateBottomFromDom = useCallback(() => {
    const el = listRef.current;
    if (!el) return;
    const distance = el.scrollHeight - (el.scrollTop + el.clientHeight);
    updateBottomFlags(distance <= CHAT_BOTTOM_THRESHOLD_PX);
  }, [updateBottomFlags]);

  useEffect(() => {
    const raf = requestAnimationFrame(() => {
      updateBottomFromDom();
    });
    return () => {
      cancelAnimationFrame(raf);
    };
  }, [renderTurns.length, updateBottomFromDom]);

  useEffect(() => {
    const el = listRef.current;
    if (!el) return;
    updateBottomFromDom();
    const onScroll = () => {
      if (scrollListenerFrameRef.current !== null) return;
      scrollListenerFrameRef.current = requestAnimationFrame(() => {
        scrollListenerFrameRef.current = null;
        updateBottomFromDom();
      });
    };
    el.addEventListener("scroll", onScroll, { passive: true });
    return () => {
      el.removeEventListener("scroll", onScroll);
      if (scrollListenerFrameRef.current !== null) {
        cancelAnimationFrame(scrollListenerFrameRef.current);
        scrollListenerFrameRef.current = null;
      }
    };
  }, [updateBottomFromDom]);

  const scrollToLatest = useCallback(
    (reason: "assistant_new_message" | "session_initial_load") => {
      const el = listRef.current;
      if (!el || renderTurns.length === 0) return;
      virtualizerDebugRef.current.scrollToIndexCalls += 1;
      if (pendingScrollToLatestRafRef.current !== null) {
        cancelAnimationFrame(pendingScrollToLatestRafRef.current);
      }
      pendingScrollToLatestRafRef.current = requestAnimationFrame(() => {
        pendingScrollToLatestRafRef.current = null;
        el.scrollTo({ top: el.scrollHeight, behavior: reason === "session_initial_load" ? "auto" : "smooth" });
        if (reason === "session_initial_load") {
          updateBottomFromDom();
        }
      });
    },
    [renderTurns.length, updateBottomFromDom]
  );

  useEffect(() => {
    return () => {
      if (pendingScrollToLatestRafRef.current !== null) {
        cancelAnimationFrame(pendingScrollToLatestRafRef.current);
        pendingScrollToLatestRafRef.current = null;
      }
    };
  }, []);

  useEffect(() => {
    pendingInitialScrollSessionRef.current = activeSessionId;
    lastAssistantMarkerRef.current = "";
    atBottomRef.current = true;
    autoScrollEnabledRef.current = true;
  }, [activeSessionId]);

  useEffect(() => {
    if (!activeSessionId || renderTurns.length === 0) return;
    if (pendingInitialScrollSessionRef.current !== activeSessionId) return;
    pendingInitialScrollSessionRef.current = null;
    scrollToLatest("session_initial_load");
  }, [activeSessionId, renderTurns.length, scrollToLatest]);

  const latestAssistantMarker = useMemo(() => {
    for (let i = turns.length - 1; i >= 0; i -= 1) {
      const turn = turns[i];
      if (turn.role === "assistant") {
        return `${turn.created_at}:${turn.content.length}`;
      }
    }
    return "";
  }, [turns]);

  useEffect(() => {
    if (!latestAssistantMarker) return;
    if (!lastAssistantMarkerRef.current) {
      lastAssistantMarkerRef.current = latestAssistantMarker;
      return;
    }
    if (lastAssistantMarkerRef.current === latestAssistantMarker) return;
    lastAssistantMarkerRef.current = latestAssistantMarker;
    if (pendingInitialScrollSessionRef.current === activeSessionId) return;
    if (!autoScrollEnabledRef.current || !atBottomRef.current) return;
    scrollToLatest("assistant_new_message");
  }, [activeSessionId, latestAssistantMarker, scrollToLatest]);

  useEffect(() => {
    if (!pendingAssistantTurn) return;
    if (!autoScrollEnabledRef.current || !atBottomRef.current) return;
    scrollToLatest("assistant_new_message");
  }, [pendingAssistantTurn, scrollToLatest]);

  const dispatchMessage = useCallback(async (text: string) => {
    const message = text.trim();
    if (!message || sending) return;
    setSending(true);
    setPendingMessage(message);
    try {
      await sendChat(message);
      setInput("");
    } catch (err) {
      pushToast(messages.toast.chatFailed, err instanceof Error ? err.message : messages.toast.unknownError, "error");
    } finally {
      setSending(false);
      setPendingMessage("");
    }
  }, [pushToast, sendChat, sending]);

  const handleCardAction = useCallback(
    (action: string, payload?: Record<string, unknown>) => {
      if (action === "followup_prompt") {
        const prompt = String(payload?.message ?? "").trim();
        if (!prompt) {
          pushToast("Action unavailable", "No follow-up prompt provided.", "error");
          return;
        }
        void dispatchMessage(prompt);
        return;
      }
      if (action === "refresh_evidence") {
        const market = String(payload?.market ?? "market");
        void dispatchMessage(`Refresh evidence and summarize latest drivers and risks for ${market}.`);
        return;
      }
      if (action === "open_evidence_pack") {
        if (typeof window !== "undefined") {
          window.location.assign("/evidence");
        }
        return;
      }
      if (action === "open_result") {
        const path = String(payload?.path ?? "").trim();
        if (typeof window !== "undefined") {
          if (path) {
            const nextPath = path.startsWith("/") ? path : `/${path}`;
            window.location.assign(nextPath);
            return;
          }
          const taskId = String(payload?.task_id ?? "").trim();
          if (taskId) {
            window.location.assign(`/tasks?focus_task_id=${encodeURIComponent(taskId)}`);
            return;
          }
        }
        return;
      }
      if (action === "open_task") {
        const parentTaskId = String(payload?.parent_task_id ?? "").trim();
        if (typeof window !== "undefined") {
          const path = parentTaskId ? `/tasks?focus_task_id=${encodeURIComponent(parentTaskId)}` : "/tasks";
          window.location.assign(path);
        }
        return;
      }
      pushToast("Action queued", "This next-step action has been captured.", "default");
    },
    [dispatchMessage, pushToast]
  );

  async function onSend(e: FormEvent) {
    e.preventDefault();
    await dispatchMessage(input);
  }

  async function submitUnlockRequest(e: FormEvent) {
    e.preventDefault();
    if (!unlockAck) {
      pushToast("Risk statement required", messages.toast.riskAckRequired, "error");
      return;
    }
    await requestApproval({
      target: "live_trading",
      use_case: unlockUseCase.trim(),
      plan_id: unlockPlanId || latestSession?.last_plan_id || "",
      session_id: activeSessionId || undefined,
      risk_statement_ack: unlockAck,
    });
    setUnlockUseCase("");
    setUnlockAck(false);
  }

  return (
    <div className="grid gap-4 xl:grid-cols-12">
      <Card className="xl:col-span-3">
        <CardHeader>
          <CardTitle>{messages.chat.sessions}</CardTitle>
          <CardDescription>{messages.chat.sessionsDesc}</CardDescription>
        </CardHeader>
        <CardContent>
          {loadingCore ? (
            <div className="space-y-2">
              {Array.from({ length: 6 }).map((_, i) => (
                <Skeleton key={i} className="h-10 w-full" />
              ))}
            </div>
          ) : chatSessions.length === 0 ? (
            <EmptyState title={messages.chat.noSessionsTitle} description={messages.chat.noSessionsDesc} />
          ) : (
            <div className="space-y-2">
              {chatSessions.map((session) => (
                <button
                  key={session.session_id}
                  onClick={() => {
                    void selectSession(session.session_id);
                  }}
                  className={`w-full rounded-lg border p-2 text-left text-xs transition-colors ${
                    activeSessionId === session.session_id ? "border-primary bg-primary/10" : "hover:bg-accent/60"
                  }`}
                >
                  <p className="truncate font-medium">{session.last_message || "(empty)"}</p>
                  <p className="mt-1 text-muted-foreground">{new Date(session.updated_at).toLocaleString()}</p>
                </button>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      <Card className="xl:col-span-6">
        <CardHeader className="flex-row items-center justify-between">
          <div>
            <CardTitle>{messages.chat.workspace}</CardTitle>
            <CardDescription>{messages.chat.workspaceDesc}{refreshingCore ? " (background refresh...)" : ""}</CardDescription>
          </div>
          <Badge variant={mode === "developer" ? "warning" : "success"}>{mode === "developer" ? messages.chat.developerMode : messages.chat.userMode}</Badge>
        </CardHeader>
        <CardContent>
          {restoredTraceId ? (
            <div className="mb-3 rounded-md border border-success/40 bg-success/5 p-2 text-xs text-success">
              {messages.chat.restoredBanner.replace("{traceId}", restoredTraceId)}
            </div>
          ) : null}

          <div ref={listRef} className="scrollbar-thin mb-3 h-[58vh] min-h-[420px] overflow-y-auto rounded-lg border p-3">
            {renderTurns.length === 0 ? (
              <EmptyState title={messages.chat.firstThreadTitle} description={messages.chat.firstThreadDesc} />
            ) : (
              <div className="space-y-2">
                {renderTurnRows.map(({ key, turn }) => (
                  <div key={key} className="pb-2">
                    <TurnCard turn={turn} mode={mode} onAction={handleCardAction} taskById={taskById} />
                  </div>
                ))}
              </div>
            )}
          </div>
          <form onSubmit={onSend} className="flex gap-2">
            <Input value={input} onChange={(e) => setInput(e.target.value)} placeholder={messages.chat.askPlaceholder} />
            <Button type="submit" disabled={sending}>{sending ? messages.chat.running : messages.chat.send}</Button>
          </form>

          <div className="mt-3 flex gap-2">
            {mode === "developer" ? (
              <Button variant="outline" onClick={() => setEventsOpen(true)}>
                <Code2 className="mr-1 h-4 w-4" />
                {messages.chat.openRawEvents}
              </Button>
            ) : null}
            {latestSession?.last_run_id ? <Link href={`/reports/${latestSession.last_run_id}`} className="inline-flex items-center text-xs text-primary underline">Open latest run report</Link> : null}
          </div>

          {mode === "developer" ? (
            <DebugPanel
              virtualizerDebugRef={virtualizerDebugRef}
              atBottomRef={atBottomRef}
              autoScrollEnabledRef={autoScrollEnabledRef}
              sseConnectionState={sseConnectionState}
            />
          ) : null}
        </CardContent>
      </Card>

      <Card className="xl:col-span-3">
        <CardHeader>
          <CardTitle>{messages.chat.tradingConsole}</CardTitle>
          <CardDescription>{messages.chat.tradingConsoleDesc}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="rounded-lg border p-3">
            <p className="text-xs text-muted-foreground">{messages.chat.liveLockStatus}</p>
            <div className="mt-1 flex flex-wrap gap-1">
              <Badge variant={(risk?.live_trading_enabled ?? false) ? "destructive" : "muted"}>{risk?.live_trading_enabled ? "enabled" : (risk?.live_approval_state ?? "locked")}</Badge>
              <Badge variant="muted">{messages.chat.pendingCount} {approvals.filter((a) => a.status === "pending").length}</Badge>
              <Badge variant="muted">{messages.chat.killSwitch} {risk?.kill_switch_enabled ? messages.chat.on : messages.chat.off}</Badge>
            </div>
            {mode === "developer" && riskSnapshotTs ? (
              <p className="mt-1 text-[11px] text-muted-foreground">{`snapshot_at=${riskSnapshotTs}`}</p>
            ) : null}
          </div>

          <div className="rounded-lg border p-3">
            <p className="text-xs text-muted-foreground">{messages.chat.paperControls}</p>
            <div className="mt-2 flex gap-2">
              <Button size="sm" onClick={() => void setPaperRunning(true)} disabled={risk?.paper_trading_enabled === true}>{messages.chat.start}</Button>
              <Button size="sm" variant="outline" onClick={() => void setPaperRunning(false)} disabled={risk?.paper_trading_enabled === false}>{messages.chat.stop}</Button>
            </div>
            <p className="mt-1 text-xs text-muted-foreground">{messages.chat.status}: {risk?.paper_trading_enabled ? messages.chat.runningLabel : messages.chat.stoppedLabel}</p>
          </div>

          <form onSubmit={submitUnlockRequest} className="space-y-2 rounded-lg border p-3">
            <p className="text-xs text-muted-foreground">{messages.chat.requestUnlock}</p>
            <Input value={unlockUseCase} onChange={(e) => setUnlockUseCase(e.target.value)} placeholder={messages.chat.useCasePlaceholder} />
            <select value={unlockPlanId} onChange={(e) => setUnlockPlanId(e.target.value)} className="h-9 w-full rounded-md border border-input bg-background px-3 text-xs">
              <option value="">{messages.chat.planIdAuto}</option>
              {planOptions.map((planId) => (
                <option key={planId} value={planId}>{planId}</option>
              ))}
            </select>
            <label className="flex items-center gap-2 text-xs text-muted-foreground">
              <input type="checkbox" checked={unlockAck} onChange={(e) => setUnlockAck(e.target.checked)} className="h-3.5 w-3.5" />
              {messages.chat.riskAck}
            </label>
            <Button type="submit" size="sm" className="w-full">{messages.chat.submitUnlock}</Button>
          </form>

          <div className="rounded-lg border p-3">
            <p className="mb-2 text-xs text-muted-foreground">{messages.chat.approvalsRealtime}</p>
            {approvals.length === 0 ? (
              <p className="text-xs text-muted-foreground">{messages.chat.noApprovals}</p>
            ) : (
              <div className="space-y-2">
                {approvals.slice(0, 8).map((row) => (
                  <div key={row.request_id} className="rounded border p-2">
                    <p className="truncate text-[11px]">{row.request_id}</p>
                    <p className="mt-1 text-[11px] text-muted-foreground">{row.target} / {row.status}</p>
                    <div className="mt-2 flex gap-1">
                      <Button size="sm" variant="secondary" disabled={row.status !== "pending"} onClick={() => void approveApproval(row.request_id)}>{messages.chat.approve}</Button>
                      <Button size="sm" variant="outline" disabled={row.status !== "approved"} onClick={() => void enableApproval(row.request_id)}>{messages.chat.enable}</Button>
                      <Button size="sm" variant="destructive" disabled={row.status === "revoked" || row.status === "expired"} onClick={() => void revokeApproval(row.request_id)}>{messages.chat.revoke}</Button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </CardContent>
      </Card>

      <Sheet open={eventsOpen} onOpenChange={setEventsOpen}>
        <SheetContent side="right">
          <SheetHeader>
            <SheetTitle className="flex items-center gap-2"><FileText className="h-4 w-4" />{messages.chat.rawEvents}</SheetTitle>
            <SheetDescription>{messages.chat.rawEventsDesc}</SheetDescription>
          </SheetHeader>
          <div className="mt-3 flex gap-1">
            <Button size="sm" variant={tracePanelTab === "live_trace" ? "secondary" : "outline"} onClick={() => setTracePanelTab("live_trace")}>
              Live Trace
            </Button>
            <Button
              size="sm"
              variant={tracePanelTab === "reasoning_steps" ? "secondary" : "outline"}
              onClick={() => setTracePanelTab("reasoning_steps")}
            >
              Reasoning Steps
            </Button>
          </div>

          {tracePanelTab === "live_trace" ? (
            <>
              <div className="mt-3 flex flex-wrap gap-1">
                {[
                  { key: "all", label: "All" },
                  { key: "agent", label: "Agent" },
                  { key: "tool", label: "Tool" },
                  { key: "artifact", label: "Artifact" },
                  { key: "audit", label: "Audit" },
                ].map((row) => (
                  <Button
                    key={row.key}
                    size="sm"
                    variant={traceFilter === row.key ? "secondary" : "outline"}
                    onClick={() => setTraceFilter(row.key as "all" | "agent" | "tool" | "artifact" | "audit")}
                  >
                    {row.label}
                  </Button>
                ))}
              </div>
              <div className="scrollbar-thin mt-3 h-[76%] space-y-2 overflow-auto rounded-md border p-2">
                {liveTraceEvents.map((ev, idx) => {
                  const payload = asRecord(ev.payload);
                  const openPathRaw = String(payload.open_path ?? "").trim();
                  const runId = String(payload.run_id ?? "").trim();
                  const planId = String(payload.plan_id ?? "").trim();
                  const evidencePackId = String(payload.artifact_id ?? "").trim();
                  const openPath = openPathRaw || (runId ? `/reports/${runId}` : planId ? `/plan/${planId}` : "");
                  const summary = String(payload.status_text ?? payload.summary ?? payload.message ?? "").trim();
                  return (
                    <div key={`${ev.event_id ?? "evt"}:${idx}`} className="rounded border bg-background p-2 text-[11px]">
                      <p className="font-semibold">{ev.type}</p>
                      <p className="text-muted-foreground">{`ts=${ev.timestamp} trace=${ev.trace_id}`}</p>
                      {summary ? <p className="mt-1 text-muted-foreground">{summary}</p> : null}
                      {openPath ? (
                        <div className="mt-1">
                          <Button
                            size="sm"
                            variant="outline"
                            onClick={() => {
                              if (typeof window !== "undefined") window.location.assign(openPath.startsWith("/") ? openPath : `/${openPath}`);
                            }}
                          >
                            Open Artifact
                          </Button>
                        </div>
                      ) : null}
                      {!openPath && evidencePackId && String(payload.artifact_type ?? "") === "evidence_pack" ? (
                        <div className="mt-1">
                          <Button
                            size="sm"
                            variant="outline"
                            onClick={() => {
                              if (typeof window !== "undefined") window.location.assign("/evidence");
                            }}
                          >
                            Open Evidence
                          </Button>
                        </div>
                      ) : null}
                      <details className="mt-1">
                        <summary className="cursor-pointer text-muted-foreground">payload</summary>
                        <pre className="mt-1 whitespace-pre-wrap text-[10px] text-muted-foreground">{JSON.stringify(payload, null, 2)}</pre>
                      </details>
                    </div>
                  );
                })}
                {liveTraceEvents.length === 0 ? (
                  <p className="p-2 text-[11px] text-muted-foreground">No events in this filter.</p>
                ) : null}
              </div>
            </>
          ) : (
            <div className="scrollbar-thin mt-3 h-[82%] space-y-2 overflow-auto rounded-md border p-2">
              {reasoningStepEvents.map((step) => (
                <div key={`${step.trace_id}:${step.agent_name}:${step.step_idx}`} className="rounded border bg-background p-2 text-[11px]">
                  <p className="font-semibold">{`${step.agent_name} · #${step.step_idx} · ${step.step_type}`}</p>
                  <p className="text-muted-foreground">{step.title || "Reasoning step"}</p>
                  {step.summary ? <p className="mt-1 text-muted-foreground">{step.summary}</p> : null}
                  {step.parse_error ? <p className="mt-1 text-destructive">{`parse_error=${step.parse_error}`}</p> : null}
                  {step.prompt_hash ? <p className="mt-1 text-muted-foreground">{`prompt_hash=${step.prompt_hash}`}</p> : null}
                  {step.evidence_refs.length > 0 ? (
                    <details className="mt-1">
                      <summary className="cursor-pointer text-muted-foreground">evidence refs</summary>
                      <div className="mt-1 space-y-1 text-[10px] text-muted-foreground">
                        {step.evidence_refs.map((row) => (
                          <p key={`${step.step_idx}:${row.source_id}`}>{`${row.source_id} ${row.title ? `· ${row.title}` : ""}${row.ts ? ` · ${row.ts}` : ""}`}</p>
                        ))}
                      </div>
                    </details>
                  ) : null}
                  <div className="mt-2">
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={async () => {
                        try {
                          if (typeof navigator !== "undefined" && navigator.clipboard?.writeText) {
                            await navigator.clipboard.writeText(JSON.stringify(step.raw, null, 2));
                            pushToast("Copied", "Reasoning step JSON copied.", "success");
                          }
                        } catch {
                          pushToast("Copy failed", "Clipboard unavailable.", "error");
                        }
                      }}
                    >
                      Copy JSON
                    </Button>
                  </div>
                </div>
              ))}
              {reasoningStepEvents.length === 0 ? (
                <p className="p-2 text-[11px] text-muted-foreground">No reasoning steps yet.</p>
              ) : null}
              {reasoningTraceFinalEvents.length > 0 ? (
                <div className="rounded border bg-background p-2 text-[11px]">
                  <p className="font-semibold">Trace Finals</p>
                  {reasoningTraceFinalEvents.map((ev) => {
                    const payload = asRecord(ev.payload);
                    return (
                      <p key={String(ev.event_id ?? ev.timestamp)} className="mt-1 text-muted-foreground">
                        {`${String(payload.agent_name ?? "agent")} · steps=${String(payload.steps_count ?? "-")} · parse_error=${String(payload.has_parse_error ?? false)}`}
                      </p>
                    );
                  })}
                </div>
              ) : null}
            </div>
          )}
        </SheetContent>
      </Sheet>
    </div>
  );
}
