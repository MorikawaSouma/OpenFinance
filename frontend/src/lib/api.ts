import type {
  ApprovalRequest,
  BacktestReport,
  ChatResponse,
  ChatSessionSummary,
  ChatTurn,
  DatasetEntry,
  EvidencePack,
  EvidencePackSummary,
  FactorDetail,
  FactorMultiMarketCompareRequest,
  FactorMultiMarketCompareResponse,
  FactorRunResponse,
  FactorSummary,
  ResearchPlan,
  PipelineResponse,
  RestoreBundle,
  PlanCreateResponse,
  MultiMarketCompareRequest,
  MultiMarketCompareResponse,
  RobustnessReport,
  RobustnessRunRequest,
  RiskStatus,
  RiskEventRow,
  RunSummary,
  SimBrokerLog,
  StrategyDetail,
  StrategySummary,
  TaskRecord,
} from "@/lib/types";
import { safeJson } from "@/lib/utils";

function normalizeApiBase(input?: string): string {
  const value = (input ?? "").trim().replace(/^['"]|['"]$/g, "");
  if (!value) return "http://127.0.0.1:8000";
  return value.replace(/\s+/g, "").replace(/\/+$/, "");
}

export const API_BASE = normalizeApiBase(process.env.NEXT_PUBLIC_API_BASE);

function buildUrl(path: string): string {
  return new URL(path, `${API_BASE}/`).toString();
}

const FALLBACK_BASES = Array.from(
  new Set(
    [
      API_BASE,
      "http://127.0.0.1:8010",
      "http://localhost:8010",
      "http://127.0.0.1:8000",
      "http://localhost:8000",
    ].map((value) => normalizeApiBase(value))
  )
);

async function tryFetch(url: string, init?: RequestInit): Promise<Response> {
  return fetch(url, init);
}

async function get<T>(path: string): Promise<T> {
  let lastNetworkError: unknown = null;
  for (const base of FALLBACK_BASES) {
    const url = new URL(path, `${base}/`).toString();
    try {
      const res = await tryFetch(url);
      return safeJson<T>(res);
    } catch (err) {
      // `safeJson` throws for HTTP errors; keep behavior deterministic and do not fallback on HTTP-level failures.
      if (err instanceof Error && err.message.startsWith("HTTP ")) {
        throw err;
      }
      lastNetworkError = err;
    }
  }
  throw new Error(
    `Network error calling ${buildUrl(path)}: ${
      lastNetworkError instanceof Error ? lastNetworkError.message : "unknown"
    }`
  );
}

async function post<T>(path: string, body: Record<string, unknown>): Promise<T> {
  let lastNetworkError: unknown = null;
  for (const base of FALLBACK_BASES) {
    const url = new URL(path, `${base}/`).toString();
    try {
      const res = await tryFetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      return safeJson<T>(res);
    } catch (err) {
      if (err instanceof Error && err.message.startsWith("HTTP ")) {
        throw err;
      }
      lastNetworkError = err;
    }
  }
  throw new Error(
    `Network error calling ${buildUrl(path)}: ${
      lastNetworkError instanceof Error ? lastNetworkError.message : "unknown"
    }`
  );
}

export const api = {
  getTasks: () => get<TaskRecord[]>("/workbench/tasks"),
  getTask: (taskId: string) => get<TaskRecord>(`/workbench/tasks/${taskId}`),
  getDatasets: () => get<DatasetEntry[]>("/workbench/datasets"),
  getDataset: (datasetVersion: string) => get<DatasetEntry>(`/workbench/datasets/${datasetVersion}`),
  getRuns: () => get<RunSummary[]>("/workbench/runs"),
  getRun: (runId: string) => get<BacktestReport>(`/workbench/runs/${runId}`),
  getReports: () => get<RunSummary[]>("/workbench/runs"),
  getStrategies: () => get<StrategySummary[]>("/workbench/strategies"),
  getStrategy: (version: string) => get<StrategyDetail>(`/workbench/strategies/${version}`),
  getFactors: () => get<FactorSummary[]>("/workbench/factors"),
  getFactor: (version: string) => get<FactorDetail>(`/workbench/factors/${version}`),
  runFactor: (payload: Record<string, unknown>) => post<FactorRunResponse>("/workbench/factors/run", payload),
  compareFactorMultiMarket: (payload: FactorMultiMarketCompareRequest) =>
    post<FactorMultiMarketCompareResponse>("/workbench/factor/multi_market_compare", payload),
  getRiskStatus: () => get<RiskStatus>("/trading/status"),
  getRiskEvents: (limit = 50) => get<RiskEventRow[]>(`/trading/risk/events?limit=${limit}`),
  updateRiskHeartbeat: (payload: {
    account_equity: number;
    source?: string;
    metrics?: Record<string, number | string>;
  }) => post<RiskStatus>("/trading/risk/heartbeat", payload),
  getEvidencePacks: () => get<EvidencePackSummary[]>("/knowledge/evidence/packs"),
  getEvidencePack: (packId: string) => get<EvidencePack>(`/knowledge/evidence/packs/${packId}`),
  getAudit: (traceId?: string) => get<Record<string, unknown>[]>(`/workbench/audit${traceId ? `?trace_id=${traceId}` : ""}`),
  generateDataset: (payload: Record<string, unknown>) => post<TaskRecord>("/workbench/datasets/generate", payload),
  runBacktest: (payload: Record<string, unknown>) => post<TaskRecord>("/workbench/backtests/run", payload),
  createPlan: (payload: Record<string, unknown>) =>
    post<PlanCreateResponse>("/plan", payload),
  getPlan: (planId: string) => get<ResearchPlan>(`/plan/${planId}`),
  runPlan: (payload: Record<string, unknown>) => post<PipelineResponse>("/run", payload),
  runPipeline: (payload: Record<string, unknown>) => post<PipelineResponse>("/pipeline/run", payload),
  restoreTrace: (traceId: string, sessionId?: string) =>
    get<RestoreBundle>(`/trace/${traceId}/restore${sessionId ? `?session_id=${encodeURIComponent(sessionId)}` : ""}`),
  compareMultiMarket: (payload: MultiMarketCompareRequest) =>
    post<MultiMarketCompareResponse>("/workbench/reports/multi-market/compare", payload),
  runRobustness: (payload: RobustnessRunRequest) => post<RobustnessReport>("/workbench/reports/robustness/run", payload),
  sendChat: (payload: Record<string, unknown>) => post<ChatResponse>("/chat/message", payload),
  getChatSessions: () => get<ChatSessionSummary[]>("/chat/sessions"),
  getChatSessionTurns: (sessionId: string) => get<ChatTurn[]>(`/chat/sessions/${sessionId}`),
  setKillSwitch: (enabled: boolean) => post<RiskStatus>("/trading/kill-switch", { enabled }),
  setLiveUnlock: (enabled: boolean) => post<RiskStatus>("/trading/live/unlock", { enabled }),
  setPaperRunning: (enabled: boolean) => post<RiskStatus>("/trading/paper/control", { enabled }),
  getLiveLogs: (limit = 200) => get<SimBrokerLog[]>(`/trading/live/logs?limit=${limit}`),
  placeLiveOrder: (payload: Record<string, unknown>) => post<Record<string, unknown>>("/trading/live/orders", payload),
  getApprovals: () => get<ApprovalRequest[]>("/trading/approvals"),
  getApproval: (requestId: string) => get<ApprovalRequest>(`/trading/approvals/${requestId}`),
  requestApproval: (payload: {
    target: "live_trading" | "paper_trading";
    use_case?: string;
    plan_id?: string;
    evidence_pack_id?: string;
    session_id?: string;
    risk_statement_ack?: boolean;
  }) => post<ApprovalRequest>("/trading/approvals/request", payload),
  approveApproval: (requestId: string, actor = "admin") =>
    post<ApprovalRequest>(`/trading/approvals/${requestId}/approve`, { actor }),
  enableApproval: (requestId: string, actor = "admin") =>
    post<ApprovalRequest>(`/trading/approvals/${requestId}/enable`, { actor }),
  revokeApproval: (requestId: string, actor = "admin") =>
    post<ApprovalRequest>(`/trading/approvals/${requestId}/revoke`, { actor }),
};
