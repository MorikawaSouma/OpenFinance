export type Mode = "user" | "developer";

export type TaskRecord = {
  task_id: string;
  task_type: string;
  status: string;
  progress: number;
  message: string;
  result: Record<string, unknown>;
  error?: string | null;
};

export type DatasetEntry = {
  dataset_id: string;
  dataset_version: string;
  schema_version: string;
  seed: number;
  generation_config: Record<string, unknown>;
  lineage: Record<string, unknown>;
  quality_report: Record<string, unknown>;
  artifact_path: string;
};

export type RunSummary = {
  run_id: string;
  audit_trace_id?: string | null;
  dataset_version: string;
  strategy_id: string;
  strategy_version: string;
  market: string;
  start: string;
  end: string;
  sharpe: number | null;
  max_drawdown: number | null;
};

export type StrategySummary = {
  strategy_id: string;
  strategy_version: string;
  status: string;
  notes: string;
};

export type CircuitBreakerRule = {
  type: "consecutive_losses" | "drawdown" | "vol_spike" | string;
  threshold: number;
  cool_down_days: number;
};

export type CircuitBreakerSpec = {
  enabled: boolean;
  rule: CircuitBreakerRule;
};

export type StrategyDetail = {
  strategy_id: string;
  strategy_version: string;
  market: string;
  rebalance: string;
  strategy_family?: string;
  lookback_days?: number;
  risk_budget?: string;
  risk_constraints: Record<string, unknown>;
  circuit_breaker: CircuitBreakerSpec;
  failure_regimes: string[];
  notes: string;
};

export type FactorSummary = {
  factor_id: string;
  version: string;
  dataset_schema_version: string;
  inputs_signature: string;
  availability_lag: string;
  created_at: string;
  has_report: boolean;
};

export type FactorDetail = {
  factor_id: string;
  version: string;
  dataset_schema_version: string;
  inputs_signature: string;
  availability_lag: string;
  created_at: string;
  spec: Record<string, unknown>;
  report?: Record<string, unknown> | null;
};

export type FactorRunResponse = {
  factor_id: string;
  factor_version: string;
  dataset_version: string;
  artifact_path: string;
  cached: boolean;
  report: Record<string, unknown>;
};

export type FactorMultiMarketCompareRequest = {
  factor_id?: string;
  factor_versions?: string[];
  factor_spec?: Record<string, unknown>;
  markets: string[];
  universe?: string[];
  symbol_map?: Record<string, string>;
  start?: string;
  end?: string;
  seed?: number;
  eval_metrics?: string[];
};

export type FactorMarketMetricRow = {
  market: string;
  factor_id: string;
  factor_version: string;
  dataset_version: string;
  ic_mean: number;
  rank_ic_mean: number;
  coverage: number;
  turnover_proxy: number;
  in_sample_ic_mean: number;
  out_sample_ic_mean: number;
  oos_gap: number;
  avg_spread_bps: number;
  decay_ratio: number;
  decay_half_life_lag: number;
  estimated_cost_pressure: number;
  cost_sensitivity_level: string;
};

export type FactorMarketDecayCurve = {
  market: string;
  factor_id: string;
  factor_version: string;
  points: Array<{ lag: number; ic: number }>;
};

export type FactorMultiMarketCompareResponse = {
  compare_id: string;
  requested_metrics: string[];
  per_market_metrics: FactorMarketMetricRow[];
  per_market_decay_curves: FactorMarketDecayCurve[];
  summary_insights: string[];
};

export type BacktestReport = {
  run_id: string;
  dataset_version: string;
  strategy_version: string;
  strategy_decision?: Record<string, unknown>;
  factor_versions: Array<{
    factor_id: string;
    version: string;
  }>;
  factor_versions_reason?: string | null;
  audit_trace_id: string;
  created_at: string;
  metrics: Record<string, number | string>;
  charts: string[];
  diagnostics: Record<string, unknown>;
  evidence_refs: string[];
  equity_curve: Array<Record<string, number | string>>;
  orders: Array<{
    order_id: string;
    time: string;
    instrument: string;
    side: string;
    qty: number;
    order_type: string;
    limit_price: number | null;
    status: string;
    reason_code?: string;
    reason_msg?: string;
    user_friendly_msg?: string;
    reason: string;
  }>;
  trades: Array<{
    trade_id: string;
    order_id: string;
    time: string;
    instrument: string;
    side: string;
    price: number;
    qty: number;
    commission: number;
    slippage: number;
  }>;
  positions: Array<{
    time: string;
    instrument: string;
    qty: number;
    avg_price: number;
    market_price: number;
    market_value: number;
    cash: number;
    equity: number;
    unrealized_pnl: number;
  }>;
  positions_ts?: Array<{
    time: string;
    instrument: string;
    qty: number;
    avg_price: number;
    market_price: number;
    market_value: number;
    cash: number;
    equity: number;
    unrealized_pnl: number;
  }>;
  cost_breakdown: Record<string, number>;
  attribution?: {
    instrument_pnl_contrib?: Record<string, number>;
    sector_pnl_contrib?: Record<string, number>;
  };
};

export type RiskStatus = {
  mode: string;
  kill_switch_enabled: boolean;
  live_trading_enabled: boolean;
  paper_trading_enabled: boolean;
  risk_max_order_qty: number;
  live_approval_state?: string | null;
  paper_approval_state?: string | null;
  pending_approval_count?: number;
  current_equity?: number;
  peak_equity?: number;
  current_drawdown?: number;
  current_volatility?: number;
  realized_volatility?: number;
  risk_status?: "normal" | "warn" | "blocked" | string;
  max_account_drawdown_limit?: number;
  abnormal_volatility_limit?: number;
  recent_risk_events?: RiskEventRow[];
};

export type RiskEventRow = {
  event_id: string;
  event_type: string;
  severity: "high" | "medium" | "low" | string;
  message: string;
  source: string;
  metrics: Record<string, number | string>;
  created_at: string;
};

export type SimBrokerLog = {
  log_id: string;
  order_id: string;
  stage: string;
  instrument_id: string;
  side: string;
  quantity: number;
  price?: number | null;
  detail: string;
  created_at: string;
};

export type ApprovalTransition = {
  from_status: string;
  to_status: string;
  actor: string;
  reason: string;
  created_at: string;
};

export type ApprovalRequest = {
  request_id: string;
  target: string;
  action: string;
  status: "requested" | "pending" | "approved" | "enabled" | "revoked" | "expired";
  context: Record<string, unknown>;
  created_at: string;
  updated_at: string;
  expires_at?: string | null;
  transitions: ApprovalTransition[];
};

export type ChatTurn = {
  role: "user" | "assistant" | "system";
  content: string;
  created_at: string;
};

export type ChatSessionSummary = {
  session_id: string;
  last_message: string;
  updated_at: string;
  last_plan_id?: string;
  last_run_id?: string;
  last_report_id?: string;
  last_dataset_version?: string;
  recent_run_ids?: string[];
};

export type ChatResponse = {
  session_id: string;
  trace_id: string;
  assistant_message: string;
  evidence_pack_id: string;
  cards: Record<string, { summary: string; items: string[] }>;
  developer_payload: Record<string, unknown>;
  turns: ChatTurn[];
};

export type EvidenceSource = {
  source_id: string;
  title: string;
  source_type?: string;
  url?: string | null;
  uri?: string | null;
  published_at?: string | null;
  timestamp?: string | null;
  snippet: string;
  full_text_ref?: string | null;
  credibility_score: number;
  time_relevance: number;
  credibility_breakdown?: Record<string, unknown>;
};

export type EvidencePack = {
  evidence_pack_id: string;
  created_at: string;
  query: string;
  sources: EvidenceSource[];
  key_points: string[];
  credibility_score: number;
  time_relevance: number;
  credibility_breakdown?: Record<string, unknown>;
};

export type EvidencePackSummary = {
  id: string;
  query: string;
  created_at: string;
  credibility_score: number;
  time_relevance?: number;
  source_count: number;
  sources: EvidenceSource[];
  credibility_breakdown?: Record<string, unknown>;
};

export type PipelineStep = {
  name: string;
  status: string;
  summary: string;
  artifacts: string[];
};

export type PreflightWarning = {
  market: string;
  severity: "warn" | "block" | string;
  code: string;
  title: string;
  explanation: string;
  suggestion?: string;
  variant_id?: string | null;
};

export type ResearchPlan = {
  plan_id: string;
  question: string;
  markets: string[];
  objectives: string[];
  constraints: Record<string, unknown>;
  evidence_queries: string[];
  candidate_factors: Array<{
    factor_id: string;
    description: string;
    source: string;
    availability_lag: string;
    rationale: string;
  }>;
  candidate_strategy_families: string[];
  experiment_matrix: Array<{
    variant_id: string;
    strategy_family: string;
    rebalance: string;
    lookback_days: number;
    signal_threshold: number;
    risk_budget: string;
    max_position: number;
  }>;
  risk_checks: string[];
  output_format: string[];
  seed: number;
  value: {
    hypotheses: string[];
    evidence_queries: string[];
    evaluation_actions: string[];
    risks: string[];
  };
  macro: {
    hypotheses: string[];
    evidence_queries: string[];
    evaluation_actions: string[];
    risks: string[];
  };
  stats: {
    hypotheses: string[];
    evidence_queries: string[];
    evaluation_actions: string[];
    risks: string[];
  };
  behavior: {
    hypotheses: string[];
    evidence_queries: string[];
    evaluation_actions: string[];
    risks: string[];
  };
};

export type ExperimentResult = {
  variant_id: string;
  strategy_family: string;
  factor_version: string;
  strategy_version: string;
  run_id: string;
  dataset_version: string;
  objective_score: number;
  metrics: Record<string, number | string>;
  strategy_spec: Record<string, unknown>;
  strategy_decision: Record<string, unknown>;
  backtest_request: Record<string, unknown>;
  why_selected: string;
};

export type PipelineResponse = {
  trace_id: string;
  question: string;
  plan_id: string;
  evidence_pack_id: string;
  evidence_sources: Array<Record<string, unknown>>;
  factor_version: string;
  strategy_version: string;
  dataset_version: string;
  run_id: string;
  backtest_metrics: Record<string, number | string>;
  strategy_config: Record<string, unknown>;
  strategy_decision: Record<string, unknown>;
  risk_explanation: string;
  research_plan: ResearchPlan;
  experiments: ExperimentResult[];
  comparison_table: Array<Record<string, unknown>>;
  interpretation: string;
  agent_outputs: Array<Record<string, unknown>>;
  preflight_warnings: PreflightWarning[];
  preflight_actions: string[];
  llm_mode: string;
  paper_trade_result?: Record<string, unknown>;
  steps: PipelineStep[];
};

export type PlanCreateResponse = {
  trace_id: string;
  plan_id: string;
  plan: ResearchPlan;
  evidence_pack_id: string;
  preflight_warnings: PreflightWarning[];
  llm_mode: string;
};

export type MultiMarketCompareRequest = {
  markets: string[];
  strategy_id: string;
  strategy_version: string;
  strategy_family: string;
  rebalance: string;
  lookback_days: number;
  signal_threshold: number;
  position_sizing: string;
  risk_budget: string;
  max_position: number;
  leverage_limit: number;
  auto_round_lot: boolean;
  start: string;
  end: string;
  seed: number;
  commission_bps: number;
  slippage_bps: number;
};

export type MultiMarketCompareRow = {
  market: string;
  run_id: string;
  dataset_version: string;
  strategy_version: string;
  metrics: Record<string, number | string>;
};

export type MigrationWarning = {
  market: string;
  code: string;
  severity: "high" | "medium" | "low" | string;
  title: string;
  explanation: string;
};

export type MultiMarketCompareResponse = {
  compare_id: string;
  baseline_market: string;
  strategy_spec: Record<string, unknown>;
  rows: MultiMarketCompareRow[];
  diff_table: Array<Record<string, number | string>>;
  migration_warnings: MigrationWarning[];
  market_warnings: Record<string, MigrationWarning[]>;
};

export type RobustnessRunRequest = {
  dataset_version?: string;
  strategy_id: string;
  strategy_version: string;
  market: string;
  start: string;
  end: string;
  strategy_family: string;
  rebalance: string;
  lookback_days: number;
  signal_threshold: number;
  position_sizing: string;
  risk_budget: string;
  max_position: number;
  leverage_limit: number;
  auto_round_lot: boolean;
  commission_bps: number;
  slippage_bps: number;
  cost_multipliers: number[];
  lookback_grid?: number[];
  threshold_grid?: number[];
  rebalance_grid?: string[];
  max_variants?: number;
};

export type RobustnessVariant = {
  variant_id: string;
  group: string;
  scenario: string;
  run_id: string;
  strategy_version: string;
  commission_bps: number;
  slippage_bps: number;
  constraints: Record<string, unknown>;
  metrics: Record<string, number | string>;
};

export type RobustnessSummary = {
  variant_count: number;
  sharpe_mean: number;
  sharpe_std: number;
  mdd_worst_case: number;
  total_return_worst_case: number;
  stability_score: number;
  best_variant_id: string;
  worst_variant_id: string;
  cost_double_impact: Record<string, number | string>;
};

export type RegimeMetric = {
  regime_id: string;
  label: string;
  start: string;
  end: string;
  bar_count: number;
  run_id: string;
  strategy_version: string;
  dataset_version: string;
  metrics: Record<string, number | string>;
};

export type StressMetric = {
  stress_id: string;
  scenario: string;
  run_id: string;
  strategy_version: string;
  dataset_version: string;
  params: Record<string, number | string>;
  metrics: Record<string, number | string>;
};

export type WorstCaseSummary = {
  source_type: string;
  scenario_id: string;
  run_id: string;
  sharpe: number;
  max_drawdown: number;
  total_return: number;
  explanation: string;
};

export type RobustnessReport = {
  robustness_id: string;
  dataset_version: string;
  strategy_id: string;
  strategy_version: string;
  market: string;
  created_at: string;
  variants: RobustnessVariant[];
  summary: RobustnessSummary;
  table: Array<Record<string, number | string>>;
  regime_metrics: RegimeMetric[];
  stress_metrics: StressMetric[];
  worst_case_summary: WorstCaseSummary;
  base_spec: Record<string, unknown>;
};

export type SseEvent = {
  type: string;
  trace_id: string;
  session_id: string;
  timestamp: string;
  payload: Record<string, unknown>;
};

export type RestoreReportHeader = {
  run_id: string;
  audit_trace_id: string;
  dataset_version: string;
  strategy_id: string;
  strategy_version: string;
  market: string;
  start: string;
  end: string;
  factor_versions: Array<Record<string, string>>;
  metrics: Record<string, unknown>;
  created_at?: string | null;
  report_path?: string | null;
  report_missing?: boolean;
};

export type RestoreBacktestRequest = {
  run_id?: string | null;
  request: Record<string, unknown>;
  source: string;
};

export type RestoreBundle = {
  trace_id: string;
  partial_restore: boolean;
  missing: string[];
  summary: string;
  plan?: Record<string, unknown> | null;
  evidence_packs: Array<Record<string, unknown>>;
  agent_outputs: Array<Record<string, unknown>>;
  backtest_requests: RestoreBacktestRequest[];
  reports_headers: RestoreReportHeader[];
  session_state: {
    session_id: string;
    last_plan_id?: string | null;
    last_run_id?: string | null;
    last_report_id?: string | null;
    last_dataset_version?: string | null;
    runs_by_session?: Array<Record<string, unknown>>;
    restore_message?: string;
  };
};
