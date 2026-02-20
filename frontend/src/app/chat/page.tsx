
"use client";

import Link from "next/link";
import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import { Code2, FileText } from "lucide-react";

import { EmptyState } from "@/components/common/empty-state";
import { useWorkbench } from "@/components/providers/workbench-provider";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  recordComponentMount,
  recordComponentUnmount,
  recordRender,
  resetDebugSnapshot,
  useDebugSnapshot,
} from "@/lib/debug";
import { messages } from "@/lib/messages";
import type { ChatTurn } from "@/lib/types";

type EnrichedTurn = ChatTurn & {
  cards?: Record<string, { summary: string; items: string[] }>;
  developerPayload?: Record<string, unknown>;
};

type ExpertCitation = {
  title?: string;
  timestamp?: string;
};

type ExpertOutput = {
  agent_name?: string;
  claim?: string;
  summary?: string;
  citations?: ExpertCitation[];
  reasoning_trace?: {
    steps?: Array<{
      step_type?: string;
      output_summary?: string;
    }>;
  };
  prompt_used?: string;
  raw_response?: string;
};

type PlanSectionPayload = {
  hypotheses?: string[];
  evidence_queries?: string[];
  evaluation_actions?: string[];
  risks?: string[];
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

function extractExpertOutputs(payload?: Record<string, unknown>): ExpertOutput[] {
  const value = payload?.agent_outputs;
  if (!Array.isArray(value)) return [];
  return value.filter((row): row is ExpertOutput => typeof row === "object" && row !== null);
}

function extractPlanSections(payload?: Record<string, unknown>): Record<string, PlanSectionPayload> | null {
  const value = payload?.plan_sections;
  if (!value || typeof value !== "object") return null;
  return value as Record<string, PlanSectionPayload>;
}

function stepSummary(expert: ExpertOutput, stepType: string): string {
  const steps = expert.reasoning_trace?.steps;
  if (!Array.isArray(steps)) return "";
  const found = steps.find((row) => row.step_type === stepType);
  return (found?.output_summary ?? "").trim();
}
function DebugPanel() {
  const snapshot = useDebugSnapshot();
  const fullReload = snapshot.navigationType === "reload";

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
        <p>{messages.chat.renderCount}: <span className="text-foreground">ChatPage {snapshot.renderCount.ChatPage ?? 0}</span></p>
        <p>{messages.chat.avgRenderMs}: <span className="text-foreground">ChatPage {snapshot.avgRenderMs.ChatPage ?? 0}</span></p>
        <p>{messages.chat.mounts}: <span className="text-foreground">ChatPage {snapshot.componentMounts.ChatPage ?? 0}</span></p>
        <p>{messages.chat.unmounts}: <span className="text-foreground">ChatPage {snapshot.componentUnmounts.ChatPage ?? 0}</span></p>
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

function TurnCard({ turn, mode }: { turn: EnrichedTurn; mode: "user" | "developer" }) {
  const isUser = turn.role === "user";
  const answerText = mode === "developer" || isUser ? turn.content : userSafeText(turn.content);
  const expertOutputs = extractExpertOutputs(turn.developerPayload);
  const planSections = extractPlanSections(turn.developerPayload);

  const conclusion =
    expertOutputs.length > 0
      ? expertOutputs
          .map((row) => `${row.agent_name ?? "Expert"}: ${(row.claim ?? row.summary ?? "").trim()}`)
          .filter((row) => row && !row.endsWith(": "))
          .join("\n")
      : answerText;

  const citations = expertOutputs
    .flatMap((row) => row.citations ?? [])
    .map((cite) => {
      const title = (cite.title ?? "").trim();
      const ts = (cite.timestamp ?? "n/a").trim();
      return title ? `${title} (${ts})` : "";
    })
    .filter(Boolean)
    .slice(0, 8);

  return (
    <div className={`max-w-[95%] rounded-lg p-3 text-sm ${isUser ? "ml-auto bg-primary text-primary-foreground" : "bg-muted/30"}`}>
      {isUser ? (
        <p className="whitespace-pre-wrap">{answerText}</p>
      ) : mode === "user" ? (
        <div className="space-y-2">
          <div className="rounded-md border bg-background p-2">
            <p className="text-xs font-semibold">{messages.chat.conclusion}</p>
            <p className="mt-1 whitespace-pre-wrap text-sm">{conclusion || answerText}</p>
          </div>
          <div className="rounded-md border bg-background p-2">
            <p className="text-xs font-semibold">{messages.chat.counterEvidenceHighlights}</p>
            <p className="mt-1 whitespace-pre-wrap text-xs text-muted-foreground">
              {expertOutputs.map((row) => `${row.agent_name ?? "Expert"}: ${stepSummary(row, "counterevidence_search")}`).filter((row) => !row.endsWith(": ")).join("\n") || messages.chat.noCounterEvidence}
            </p>
          </div>
          <div className="rounded-md border bg-background p-2">
            <p className="text-xs font-semibold">{messages.chat.revisedConclusion}</p>
            <p className="mt-1 whitespace-pre-wrap text-xs text-muted-foreground">
              {expertOutputs.map((row) => `${row.agent_name ?? "Expert"}: ${stepSummary(row, "revision")}`).filter((row) => !row.endsWith(": ")).join("\n") || messages.chat.noRevision}
            </p>
          </div>
          <div className="rounded-md border bg-background p-2">
            <p className="text-xs font-semibold">{messages.chat.keyEvidence}</p>
            {citations.length === 0 ? (
              <p className="mt-1 text-xs text-muted-foreground">{messages.chat.noCitation}</p>
            ) : (
              <ul className="mt-1 list-disc space-y-1 pl-5 text-xs">
                {citations.map((item, i) => (
                  <li key={`cite-${i}`}>{item}</li>
                ))}
              </ul>
            )}
          </div>
        </div>
      ) : (
        <div className="space-y-2">
          <p className="whitespace-pre-wrap text-sm">{answerText}</p>
          <details className="rounded-md border bg-background p-2">
            <summary className="cursor-pointer text-xs font-semibold">{messages.chat.expertPromptResponse}</summary>
            <pre className="mt-1 overflow-x-auto text-[11px] text-muted-foreground">{JSON.stringify(expertOutputs, null, 2)}</pre>
          </details>
          <details className="rounded-md border bg-background p-2">
            <summary className="cursor-pointer text-xs font-semibold">{messages.chat.rawPayload}</summary>
            <pre className="mt-1 overflow-x-auto text-[11px] text-muted-foreground">{JSON.stringify(turn.developerPayload ?? {}, null, 2)}</pre>
          </details>
        </div>
      )}

      {planSections ? (
        <div className="mt-2 rounded-md border bg-background p-2">
          <p className="mb-2 text-xs font-semibold">{messages.chat.planFramework}</p>
          <Tabs defaultValue="value">
            <TabsList>
              <TabsTrigger value="value">{messages.chat.value}</TabsTrigger>
              <TabsTrigger value="macro">{messages.chat.macro}</TabsTrigger>
              <TabsTrigger value="stats">{messages.chat.stats}</TabsTrigger>
              <TabsTrigger value="behavior">{messages.chat.behavior}</TabsTrigger>
            </TabsList>
            {["value", "macro", "stats", "behavior"].map((key) => {
              const section = planSections[key] ?? {};
              return (
                <TabsContent key={key} value={key} className="space-y-2 text-xs">
                  <p><span className="font-semibold">{messages.chat.hypotheses}:</span> {(section.hypotheses ?? []).join(" | ") || "-"}</p>
                  <p><span className="font-semibold">{messages.chat.evidenceQueries}:</span> {(section.evidence_queries ?? []).join(" | ") || "-"}</p>
                  <p><span className="font-semibold">{messages.chat.evaluationActions}:</span> {(section.evaluation_actions ?? []).join(" | ") || "-"}</p>
                  <p><span className="font-semibold">{messages.chat.risks}:</span> {(section.risks ?? []).join(" | ") || "-"}</p>
                </TabsContent>
              );
            })}
          </Tabs>
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
    loadingCore,
    refreshingCore,
    pushToast,
    risk,
    approvals,
    setPaperRunning,
    requestApproval,
    approveApproval,
    enableApproval,
    revokeApproval,
  } = useWorkbench();

  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [enrichedTurns, setEnrichedTurns] = useState<EnrichedTurn[]>([]);
  const [eventsOpen, setEventsOpen] = useState(false);
  const [restoredTraceId, setRestoredTraceId] = useState("");
  const [restoredSessionId, setRestoredSessionId] = useState("");
  const [restoreBannerShown, setRestoreBannerShown] = useState(false);
  const [unlockUseCase, setUnlockUseCase] = useState("");
  const [unlockPlanId, setUnlockPlanId] = useState("");
  const [unlockAck, setUnlockAck] = useState(false);

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

  const turns = useMemo<EnrichedTurn[]>(() => (enrichedTurns.length > 0 ? enrichedTurns : chatTurns), [chatTurns, enrichedTurns]);
  const latestSession = useMemo(
    () => chatSessions.find((row) => row.session_id === activeSessionId) ?? chatSessions[0] ?? null,
    [activeSessionId, chatSessions]
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

  const listRef = useRef<HTMLDivElement | null>(null);
  const rowVirtualizer = useVirtualizer({
    count: turns.length,
    getScrollElement: () => listRef.current,
    estimateSize: () => 220,
    overscan: 8,
  });

  useEffect(() => {
    if (turns.length === 0) return;
    rowVirtualizer.scrollToIndex(turns.length - 1, { align: "end" });
  }, [turns.length, rowVirtualizer]);

  async function onSend(e: FormEvent) {
    e.preventDefault();
    const text = input.trim();
    if (!text || sending) return;
    setSending(true);
    try {
      const resp = await sendChat(text);
      const next: EnrichedTurn[] = resp.turns.map((turn) => ({ ...turn }));
      for (let i = next.length - 1; i >= 0; i -= 1) {
        if (next[i].role === "assistant") {
          next[i] = { ...next[i], cards: resp.cards, developerPayload: resp.developer_payload };
          break;
        }
      }
      setEnrichedTurns(next);
      setInput("");
    } catch (err) {
      pushToast(messages.toast.chatFailed, err instanceof Error ? err.message : messages.toast.unknownError, "error");
    } finally {
      setSending(false);
    }
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
                    setEnrichedTurns([]);
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

          <div ref={listRef} className="scrollbar-thin mb-3 max-h-[58vh] overflow-y-auto rounded-lg border p-3">
            {turns.length === 0 ? (
              <EmptyState title={messages.chat.firstThreadTitle} description={messages.chat.firstThreadDesc} />
            ) : (
              <div style={{ height: `${rowVirtualizer.getTotalSize()}px`, width: "100%", position: "relative" }}>
                {rowVirtualizer.getVirtualItems().map((row) => (
                  <div
                    key={`${turns[row.index].created_at}-${row.index}`}
                    ref={rowVirtualizer.measureElement}
                    data-index={row.index}
                    style={{ position: "absolute", top: 0, left: 0, width: "100%", transform: `translateY(${row.start}px)`, paddingBottom: 8 }}
                  >
                    <TurnCard turn={turns[row.index]} mode={mode} />
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

          {mode === "developer" ? <DebugPanel /> : null}
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
          <pre className="scrollbar-thin mt-4 h-[85%] overflow-auto rounded-md border p-3 text-[11px] text-muted-foreground">{JSON.stringify(events.slice(0, 120), null, 2)}</pre>
        </SheetContent>
      </Sheet>
    </div>
  );
}
