export type Mode = "user" | "developer";

export type TaskRecord = {
  task_id: string;
  parent_task_id?: string | null;
  task_type: string;
  status: string;
  progress: number;
  message: string;
  result: Record<string, unknown>;
  result_ref?: Record<string, unknown>;
  meta?: Record<string, unknown>;
  created_at?: string;
  updated_at?: string;
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

export type StrategyProposalSpec = {
  strategy_family: string;
  rebalance: string;
  lookback_days: number;
  signal_threshold: number;
  position_sizing: string;
  risk_budget: string;
  max_position: number;
  leverage_limit: number;
  auto_round_lot: boolean;
  run_time_utc: string;
};

export type StrategyDecisionCandidate = {
  name: string;
  spec: StrategyProposalSpec;
  pros: string[];
  cons: string[];
  risks: string[];
  expected_failure_regimes: string[];
  cost_profile: string;
  why_not_selected: string;
};

export type StrategyDecisionSelected = {
  name: string;
  spec: StrategyProposalSpec;
  rationale: string;
  tradeoff_summary: string;
};

export type StrategyDecision = {
  schema_version: string;
  candidates: StrategyDecisionCandidate[];
  selected: StrategyDecisionSelected;
  llm_mode: string;
};

export type StrategyValidationCheck = {
  check_id: "spec_fields" | "decision_alignment" | "evidence_linkage" | "compile_boundary" | string;
  status: "ok" | "warn" | "invalid" | string;
  detail: string;
};

export type StrategyValidationResult = {
  schema_version: string;
  validated_object: "strategy_spec" | string;
  strategy_id: string;
  strategy_version: string;
  market: string;
  status: "ok" | "warn" | "invalid" | string;
  compile_ready: boolean;
  decision_status: "aligned" | "not_provided" | "mismatch" | string;
  selected_candidate?: string | null;
  next_output: "BacktestRequest" | string;
  summary: string;
  checks: StrategyValidationCheck[];
  evidence_refs: string[];
};

export type CompilationInputClassification =
  | "user_configurable"
  | "environment_bound"
  | "runtime_derived"
  | "validation_required_override"
  | string;

export type CompilationConfiguredBy =
  | "strategy_spec"
  | "strategy_decision"
  | "user_request"
  | "prepared_dataset"
  | "system_environment"
  | "runtime_pipeline"
  | "validation_artifact"
  | string;

export type CompilationValidatedBy =
  | "strategy_validation"
  | "compilation_profile"
  | "not_applicable"
  | string;

export type CompilationPolicyOutcome = "allowed" | "allowed_with_warning" | "blocked" | string;

export type CompilationPolicyCheckedBy =
  | "compilation_profile"
  | "migration_checker"
  | "backtest_runtime"
  | string;

export type CompilationPolicyFactSource =
  | "compilation_profile.override_policies"
  | "backtest_runner.supported_execution_models"
  | "market_rules_provider"
  | "migration_checker.warning_codes"
  | string;

export type StrategyCompilationInputPolicy = {
  output_path: string;
  classification: CompilationInputClassification;
  configured_by: CompilationConfiguredBy;
  validated_by: CompilationValidatedBy;
  source_kind?: string | null;
  source_path: string;
  rationale: string;
};

export type CompilationOverridePolicy = {
  output_path: string;
  classification: CompilationInputClassification;
  configured_by: CompilationConfiguredBy;
  source_kind: string;
  source_path: string;
  requires_additional_validation: boolean;
  rationale: string;
};

export type StrategyCompilationProfile = {
  schema_version: string;
  profile_id: string;
  executable_object: "BacktestRequest" | string;
  summary: string;
  input_policies: StrategyCompilationInputPolicy[];
  override_policies: CompilationOverridePolicy[];
};

export type StrategyCompilationPolicyCheck = {
  rule_id: string;
  code: string;
  output_path: string;
  classification: CompilationInputClassification;
  configured_by: CompilationConfiguredBy;
  outcome: CompilationPolicyOutcome;
  checked_by: CompilationPolicyCheckedBy;
  fact_source: CompilationPolicyFactSource;
  requires_additional_validation: boolean;
  detail: string;
};

export type StrategyCompilationPolicyResult = {
  schema_version: string;
  checked_object: "strategy_compilation_profile" | string;
  rule_surface_schema_version: string;
  rule_surface_id: string;
  market: string;
  environment: "backtest" | string;
  status: CompilationPolicyOutcome;
  compile_ready: boolean;
  summary: string;
  warning_count: number;
  blocked_count: number;
  checks: StrategyCompilationPolicyCheck[];
};

export type StrategyBacktestRequestInputProfile = {
  schema_version: string;
  profile_id: string;
  executable_object: "BacktestRequest" | string;
  provenance_mode: string;
  dataset_binding_source: string;
  window_source: string;
  execution_model_source: string;
  run_time_utc_source: string;
  cost_model_source: string;
  constraints_source: string;
  factor_versions_source: string;
  evaluation_plan_source: string;
  summary: string;
};

export type StrategyCompilationBinding = {
  output_path: string;
  value: unknown;
  source_kind:
    | "strategy_spec"
    | "strategy_spec.constraints"
    | "strategy_decision.selected"
    | "strategy_validation"
    | "runtime_request"
    | "default"
    | string;
  source_path: string;
  note: string;
};

export type StrategyCompilationOverlay = {
  output_path: string;
  final_value: unknown;
  source_kind:
    | "strategy_spec"
    | "strategy_spec.constraints"
    | "strategy_decision.selected"
    | "strategy_validation"
    | "runtime_request"
    | "default"
    | string;
  source_path: string;
  overridden_source_kind?: string | null;
  overridden_source_path?: string | null;
  overridden_value?: unknown;
  rationale: string;
};

export type StrategyCompilationPlan = {
  schema_version: string;
  strategy_id: string;
  strategy_version: string;
  market: string;
  executable_object: "BacktestRequest" | string;
  compile_ready: boolean;
  validation_status: "ok" | "warn" | "invalid" | string;
  decision_status: "aligned" | "not_provided" | "mismatch" | string;
  selected_candidate?: string | null;
  summary: string;
  bindings: StrategyCompilationBinding[];
  overlays: StrategyCompilationOverlay[];
  evidence_refs: string[];
  compilation_profile?: StrategyCompilationProfile | null;
  compilation_policy?: StrategyCompilationPolicyResult | null;
};

export type StrategySpec = {
  schema_version: string;
  strategy_id: string;
  strategy_version: string;
  plan_id?: string | null;
  experiment_id?: string | null;
  market: string;
  strategy_family: string;
  rebalance: string;
  lookback_days: number;
  signal_threshold: number;
  position_sizing: string;
  risk_budget: string;
  max_position: number;
  stop_loss: number;
  leverage_limit: number;
  factor_weights: Record<string, number>;
  constraints: Record<string, unknown>;
  circuit_breaker: CircuitBreakerSpec;
  failure_regimes: string[];
  rationale: string;
  evidence_refs: string[];
  simulation_only: boolean;
};

export type StrategyDetail = {
  source: "strategy_registry" | "run_registry_fallback" | "placeholder";
  created_at?: string | null;
  notes: string;
  spec: StrategySpec;
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

export type FactorRunRequest = {
  dataset_version?: string;
  factor_id: string;
  factor_version?: string;
  description?: string;
  formula: string;
  availability_lag: string;
  inputs: string[];
  failure_conditions: Array<string | Record<string, unknown>>;
  cost_sensitivity_level: string;
  cost_sensitivity_rationale: string;
  expected_horizon?: string;
  lookback_days?: number;
  decay_lags?: number;
  universe?: string[];
  seed?: number;
  session_id?: string;
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
  session_id?: string;
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
  parent_task_id?: string | null;
  child_task_ids?: string[];
};

export type BacktestReport = {
  run_id: string;
  dataset_version: string;
  market?: string;
  strategy_version: string;
  strategy_decision?: StrategyDecision | null;
  strategy_validation?: StrategyValidationResult | null;
  strategy_compilation?: StrategyCompilationPlan | null;
  strategy_trace?: StrategyTraceArtifact | null;
  runtime_summary?: StrategyRuntimeOutcomeSummary | null;
  runtime_diagnostics?: StrategyRuntimeDiagnosticsResult | null;
  action_regime_details?: StrategyRuntimeActionRegimeDetails | null;
  attribution_execution_details?: StrategyRuntimeAttributionExecutionDetails | null;
  control_optimizer_details?: StrategyRuntimeControlOptimizerDetails | null;
  control_action_deep_details?: StrategyRuntimeControlActionDeepDetails | null;
  factor_versions: FactorVersionRef[];
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

export type FactorVersionRef = {
  factor_id: string;
  version: string;
};

export type BacktestCostModel = {
  commission_bps: number;
  slippage_bps: number;
};

export type BacktestEvaluationWindow = {
  start: string;
  end: string;
};

export type BacktestEvaluationPlan = {
  schema_version: string;
  window?: BacktestEvaluationWindow | null;
  stress: string[];
  seed?: number | null;
  evidence_pack_id?: string | null;
  evidence_refs: string[];
  factor_id?: string | null;
  factor_version?: string | null;
  factor_versions: FactorVersionRef[];
  factor_artifact_path?: string | null;
  failure_conditions: unknown[];
  no_factor_strategy?: boolean | null;
  strategy_decision?: StrategyDecision | null;
  strategy_validation?: StrategyValidationResult | null;
  strategy_compilation?: StrategyCompilationPlan | null;
  request_input_profile?: StrategyBacktestRequestInputProfile | null;
  meta_variant_id?: string | null;
  meta_group?: string | null;
  [key: string]: unknown;
};

export type StrategyFactorLineageSummary = {
  factor_versions: FactorVersionRef[];
  reason?: string | null;
};

export type StrategyTraceArtifact = {
  schema_version: string;
  trace_object: "BacktestReport" | "BacktestRequest" | string;
  strategy_decision?: StrategyDecision | null;
  strategy_validation?: StrategyValidationResult | null;
  strategy_compilation?: StrategyCompilationPlan | null;
  evaluation_plan?: BacktestEvaluationPlan | null;
  factor_lineage: StrategyFactorLineageSummary;
  summary: string;
};

export type StrategyRuntimeMetricSnapshot = {
  total_return?: number | null;
  sharpe?: number | null;
  max_drawdown?: number | null;
  volatility?: number | null;
  trade_count?: number | null;
  turnover?: number | null;
  cost_drag?: number | null;
  reject_count?: number | null;
  risk_scale?: number | null;
};

export type StrategyRuntimeOutcomeSummary = {
  schema_version: string;
  summary_object: "BacktestReport" | "MarketCompareRow" | "RestoreReportHeader" | "RobustnessBase" | string;
  run_id?: string | null;
  dataset_version: string;
  market: string;
  strategy_version: string;
  metrics: StrategyRuntimeMetricSnapshot;
  compile_ready?: boolean | null;
  factor_lineage_count: number;
  evidence_ref_count: number;
  warning_count: number;
  highest_warning_severity?: string | null;
  summary: string;
};

export type StrategyCompareOutcomeSummary = {
  schema_version: string;
  summary_object: "MultiMarketCompareResponse" | string;
  compare_id: string;
  baseline_market: string;
  market_count: number;
  warning_count: number;
  best_market_by_sharpe?: string | null;
  worst_market_by_drawdown?: string | null;
  rows: StrategyRuntimeOutcomeSummary[];
  summary: string;
};

export type StrategyRobustnessOutcomeSummary = {
  schema_version: string;
  summary_object: "RobustnessReport" | string;
  robustness_id: string;
  market: string;
  variant_count: number;
  sharpe_std: number;
  mdd_worst_case: number;
  stability_score: number;
  worst_case_source_type?: string | null;
  worst_case_run_id?: string | null;
  base_runtime_summary?: StrategyRuntimeOutcomeSummary | null;
  summary: string;
};

export type StrategyRuntimeCostModelSummary = {
  commission_bps?: number | null;
  slippage_bps?: number | null;
};

export type StrategyRuntimeMarketRulesSummary = {
  market: string;
  t_plus_one?: boolean | null;
  lot_size?: number | null;
  supports_fractional_qty?: boolean | null;
  min_notional?: number | null;
  is_24x7?: boolean | null;
};

export type StrategyRuntimeRiskManagementSummary = {
  regime_vol_window?: number | null;
  regime_vol_threshold?: number | null;
  regime_exposure_scale_high_vol?: number | null;
  regime_pause_new_positions?: boolean | null;
  drawdown_limit?: number | null;
  stop_trading_triggered?: boolean | null;
  failure_condition_block_triggered?: boolean | null;
  circuit_breaker_enabled?: boolean | null;
  circuit_breaker_trigger_count: number;
};

export type StrategyRuntimePortfolioOptimizationSummary = {
  optimizer?: string | null;
  optimizer_universe_size: number;
  covariance_window?: number | null;
  max_position_weight?: number | null;
  max_gross_leverage?: number | null;
  max_sector_exposure?: number | null;
  sector_neutral?: boolean | null;
};

export type StrategyRuntimeBudgetDeviationSummary = {
  mean_l1?: number | null;
  max_l1?: number | null;
  observations: number;
};

export type StrategyRuntimeActionCounts = {
  risk_action_count: number;
  risk_actions_by_type: Record<string, number>;
  constraint_action_count: number;
  constraint_actions_by_type: Record<string, number>;
  optimizer_diagnostic_count: number;
  rejected_order_count: number;
  failure_event_count: number;
  regime_period_count: number;
};

export type StrategyRuntimeDiagnosticsResult = {
  schema_version: string;
  diagnostics_object: "BacktestReport" | "RestoreReportHeader" | string;
  execution_model: string;
  cost_model: StrategyRuntimeCostModelSummary;
  market_rules: StrategyRuntimeMarketRulesSummary;
  risk_management: StrategyRuntimeRiskManagementSummary;
  portfolio_optimization: StrategyRuntimePortfolioOptimizationSummary;
  budget_deviation: StrategyRuntimeBudgetDeviationSummary;
  action_counts: StrategyRuntimeActionCounts;
  notes?: string | null;
  summary: string;
};

export type StrategyRuntimeRiskAction = {
  time?: string | null;
  action: string;
  detail?: string | null;
};

export type StrategyRuntimeConstraintAction = {
  time?: string | null;
  optimizer?: string | null;
  symbol?: string | null;
  action: string;
  detail?: string | null;
  instrument?: string | null;
  sector?: string | null;
  before?: number | null;
  after?: number | null;
  before_gross?: number | null;
  after_gross?: number | null;
  net_before?: number | null;
  net_after?: number | null;
};

export type StrategyRuntimeFailureConditionEvent = {
  time?: string | null;
  code: string;
  level: string;
  message: string;
  metric_keys: string[];
};

export type StrategyRuntimeRegimePeriod = {
  regime: string;
  start?: string | null;
  end?: string | null;
  trigger?: string | null;
};

export type StrategyRuntimeActionRegimeDetails = {
  schema_version: string;
  detail_object: "BacktestReport" | "MarketCompareRow" | "RobustnessVariant" | "RestoreReportHeader" | string;
  risk_actions: StrategyRuntimeRiskAction[];
  constraint_actions: StrategyRuntimeConstraintAction[];
  failure_condition_events: StrategyRuntimeFailureConditionEvent[];
  regime_periods: StrategyRuntimeRegimePeriod[];
  summary: string;
};

export type StrategyRuntimeRejectedOrder = {
  time?: string | null;
  instrument?: string | null;
  side?: string | null;
  qty?: number | null;
  reason?: string | null;
  reason_code?: string | null;
  user_friendly_msg?: string | null;
  reason_msg?: string | null;
};

export type StrategyRuntimeOptimizerDiagnostic = {
  time?: string | null;
  optimizer?: string | null;
  symbol?: string | null;
  signal?: number | null;
  raw_target_exposure?: number | null;
  optimized_weight?: number | null;
  gross_target?: number | null;
  budget_deviation_l1?: number | null;
  asset_count: number;
};

export type StrategyRuntimeCircuitBreakerInterval = {
  start?: string | null;
  end?: string | null;
  reason?: string | null;
};

export type StrategyRuntimeBudgetDetail = {
  mean_l1?: number | null;
  max_l1?: number | null;
  observations: number;
  latest_time?: string | null;
  latest_deviation_l1?: number | null;
  latest_target_budget: Record<string, number>;
  latest_achieved_budget: Record<string, number>;
};

export type StrategyRuntimeRiskContributionPoint = {
  time?: string | null;
  deviation_l1?: number | null;
  target_budget: Record<string, number>;
  achieved_budget: Record<string, number>;
  weights: Record<string, number>;
};

export type StrategyRuntimeControlOptimizerDetails = {
  schema_version: string;
  detail_object: "BacktestReport" | "MarketCompareRow" | "RobustnessVariant" | "RestoreReportHeader" | string;
  rejected_orders: StrategyRuntimeRejectedOrder[];
  optimizer_diagnostics: StrategyRuntimeOptimizerDiagnostic[];
  circuit_breaker_intervals: StrategyRuntimeCircuitBreakerInterval[];
  budget_detail: StrategyRuntimeBudgetDetail;
  risk_contribution_points: StrategyRuntimeRiskContributionPoint[];
  summary: string;
};

export type StrategyRuntimeOptimizerStepDeepDetail = {
  time?: string | null;
  optimizer?: string | null;
  method?: string | null;
  asset_count: number;
  assets: string[];
  budget_deviation_l1?: number | null;
  loss_final?: number | null;
  raw_weights: Record<string, number>;
  target_budget: Record<string, number>;
  achieved_budget: Record<string, number>;
  direction: Record<string, number>;
  covariance_asset_count: number;
};

export type StrategyRuntimeCircuitBreakerExecutionSupport = {
  drawdown?: boolean | null;
  consecutive_losses?: boolean | null;
  vol_spike?: boolean | null;
};

export type StrategyRuntimeCircuitBreakerIntervalState = {
  start?: string | null;
  end?: string | null;
  reason?: string | null;
  rule_type?: string | null;
  threshold?: number | null;
  supported?: boolean | null;
};

export type StrategyRuntimeCircuitBreakerState = {
  enabled?: boolean | null;
  rule_type?: string | null;
  threshold?: number | null;
  trigger_count: number;
  stop_trading_triggered?: boolean | null;
  execution_support: StrategyRuntimeCircuitBreakerExecutionSupport;
  intervals: StrategyRuntimeCircuitBreakerIntervalState[];
};

export type StrategyRuntimeBudgetBreakdown = {
  mean_l1?: number | null;
  max_l1?: number | null;
  observations: number;
  latest_time?: string | null;
  latest_deviation_l1?: number | null;
  latest_gap_by_asset: Record<string, number>;
  peak_time?: string | null;
  peak_deviation_l1?: number | null;
  peak_gap_by_asset: Record<string, number>;
};

export type StrategyRuntimeRiskContributionSnapshot = {
  time?: string | null;
  deviation_l1?: number | null;
  target_budget: Record<string, number>;
  achieved_budget: Record<string, number>;
  weights: Record<string, number>;
  gap_by_asset: Record<string, number>;
};

export type StrategyRuntimeRiskContributionBreakdown = {
  point_count: number;
  latest?: StrategyRuntimeRiskContributionSnapshot | null;
  peak?: StrategyRuntimeRiskContributionSnapshot | null;
};

export type StrategyRuntimeControlActionDeepDetails = {
  schema_version: string;
  detail_object: "BacktestReport" | "MarketCompareRow" | "RobustnessVariant" | "RestoreReportHeader" | string;
  optimizer_steps: StrategyRuntimeOptimizerStepDeepDetail[];
  circuit_breaker_state: StrategyRuntimeCircuitBreakerState;
  budget_breakdown: StrategyRuntimeBudgetBreakdown;
  risk_contribution_breakdown: StrategyRuntimeRiskContributionBreakdown;
  summary: string;
};

export type StrategyRuntimeCostDetail = {
  commission_sum?: number | null;
  slippage_sum?: number | null;
  total_cost?: number | null;
  trade_count: number;
  order_count: number;
  avg_total_cost_per_trade?: number | null;
  avg_total_cost_per_order?: number | null;
  cost_drag?: number | null;
};

export type StrategyRuntimeAttributionRow = {
  label: string;
  pnl: number;
  abs_share?: number | null;
};

export type StrategyRuntimeAttributionDetail = {
  instrument_rows: StrategyRuntimeAttributionRow[];
  sector_rows: StrategyRuntimeAttributionRow[];
  instrument_count: number;
  sector_count: number;
  top_instrument?: StrategyRuntimeAttributionRow | null;
  worst_instrument?: StrategyRuntimeAttributionRow | null;
  top_sector?: StrategyRuntimeAttributionRow | null;
  worst_sector?: StrategyRuntimeAttributionRow | null;
};

export type StrategyRuntimeExecutionStyleDetail = {
  execution_model?: string | null;
  order_count: number;
  filled_order_count: number;
  rejected_order_count: number;
  queued_order_count: number;
  trade_count: number;
  buy_trade_count: number;
  sell_trade_count: number;
  fill_rate?: number | null;
  avg_trade_qty?: number | null;
  order_status_counts: Record<string, number>;
  reject_reason_counts: Record<string, number>;
  dominant_reject_reason?: string | null;
};

export type StrategyRuntimeAttributionExecutionDetails = {
  schema_version: string;
  detail_object: "BacktestReport" | "MarketCompareRow" | "RobustnessVariant" | "RestoreReportHeader" | string;
  cost_detail: StrategyRuntimeCostDetail;
  attribution_detail: StrategyRuntimeAttributionDetail;
  execution_style_detail: StrategyRuntimeExecutionStyleDetail;
  summary: string;
};

export type StrategyCompareDiffRow = {
  market: string;
  run_id: string;
  dataset_version: string;
  sharpe?: number | null;
  max_drawdown?: number | null;
  turnover?: number | null;
  reject_count?: number | null;
  cost_drag?: number | null;
  sharpe_diff_vs_baseline?: number | null;
  max_drawdown_diff_vs_baseline?: number | null;
  turnover_diff_vs_baseline?: number | null;
  warning_count: number;
  highest_warning_severity?: string | null;
};

export type StrategyCompareWarningSummary = {
  market: string;
  warning_count: number;
  highest_warning_severity?: string | null;
  warning_codes: string[];
};

export type StrategyCompareResultDetails = {
  schema_version: string;
  result_object: "MultiMarketCompareResponse" | string;
  compare_id: string;
  baseline_market: string;
  diff_rows: StrategyCompareDiffRow[];
  warning_summaries: StrategyCompareWarningSummary[];
  summary: string;
};

export type StrategyRobustnessVariantResultRow = {
  variant_id: string;
  group: string;
  scenario: string;
  run_id: string;
  commission_bps?: number | null;
  slippage_bps?: number | null;
  sharpe?: number | null;
  max_drawdown?: number | null;
  total_return?: number | null;
  cost_drag?: number | null;
  turnover?: number | null;
};

export type StrategyRobustnessResultDetails = {
  schema_version: string;
  result_object: "RobustnessReport" | string;
  robustness_id: string;
  variant_rows: StrategyRobustnessVariantResultRow[];
  regime_metric_count: number;
  stress_metric_count: number;
  best_variant_id?: string | null;
  worst_variant_id?: string | null;
  summary: string;
};

export type BacktestRequest = {
  dataset_version: string;
  strategy_id: string;
  strategy_version: string;
  market: string;
  start: string;
  end: string;
  execution_model: string;
  cost_model: BacktestCostModel;
  factor_versions: FactorVersionRef[];
  constraints: Record<string, unknown>;
  evaluation_plan: BacktestEvaluationPlan | Record<string, unknown>;
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
  updated_at?: string;
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
  message_id: string;
  mode: "general_info_query" | "market_compare" | "pipeline_research" | "modify_last_run" | "session_compare" | string;
  language: "zh" | "en" | string;
  assistant_message: string;
  evidence_pack_id: string;
  risk_snapshot?: {
    live_lock_status: string;
    kill_switch: boolean;
    drawdown: number;
    volatility: number;
    limits: Record<string, number>;
    risk_level: string;
    live_trading_enabled: boolean;
    paper_trading_enabled: boolean;
    updated_at: string;
  } | null;
  approvals_snapshot?: {
    items: Array<{
      request_id: string;
      status: string;
      created_at: string;
      target: string;
      use_case?: string | null;
      plan_id?: string | null;
    }>;
    updated_at: string;
  } | null;
  cards: Array<{
    card_id?: string | null;
    type:
      | "summary"
      | "drivers"
      | "watch"
      | "metrics"
      | "evidence"
      | "comparison_table"
      | "key_differences"
      | "confidence"
      | "diff"
      | "next_steps"
      | "risks"
      | string;
    title: string;
    content?: string | null;
    subtitle?: string | null;
    metrics?: Array<{ name: string; value?: string | number | null; delta?: string | number | null }>;
    items?: Array<Record<string, unknown> | string>;
    highlights?: string[];
    table?: Array<Record<string, string | number | null>>;
    actions?: Array<{ label: string; action: string; payload?: Record<string, unknown> }>;
  }>;
  debug: Record<string, unknown>;
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
  market?: string;
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
    market?: string;
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
  strategy_spec: StrategySpec;
  strategy_decision: StrategyDecision | null;
  strategy_validation: StrategyValidationResult;
  strategy_compilation: StrategyCompilationPlan;
  backtest_request: BacktestRequest;
  why_selected: string;
};

export type PipelineResponse = {
  trace_id: string;
  question: string;
  market?: string;
  plan_id: string;
  evidence_pack_id: string;
  evidence_sources: Array<Record<string, unknown>>;
  factor_version: string;
  strategy_version: string;
  dataset_version: string;
  run_id: string;
  backtest_metrics: Record<string, number | string>;
  strategy_spec: StrategySpec;
  strategy_decision: StrategyDecision | null;
  strategy_validation: StrategyValidationResult;
  strategy_compilation: StrategyCompilationPlan;
  risk_explanation: string;
  research_plan: ResearchPlan;
  experiments: ExperimentResult[];
  comparison_table: Array<Record<string, unknown>>;
  interpretation: string;
  agent_outputs: Array<Record<string, unknown>>;
  reasoning_steps: Array<Record<string, unknown>>;
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
  session_id?: string;
};

export type MultiMarketCompareRow = {
  market: string;
  run_id: string;
  dataset_version: string;
  strategy_version: string;
  metrics: Record<string, number | string>;
  action_regime_details?: StrategyRuntimeActionRegimeDetails | null;
  attribution_execution_details?: StrategyRuntimeAttributionExecutionDetails | null;
  control_optimizer_details?: StrategyRuntimeControlOptimizerDetails | null;
  control_action_deep_details?: StrategyRuntimeControlActionDeepDetails | null;
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
  strategy_spec: StrategySpec;
  strategy_validation: StrategyValidationResult;
  strategy_compilation: StrategyCompilationPlan;
  outcome_summary?: StrategyCompareOutcomeSummary | null;
  result_details?: StrategyCompareResultDetails | null;
  rows: MultiMarketCompareRow[];
  diff_table: Array<Record<string, number | string>>;
  parent_task_id?: string | null;
  child_task_ids?: string[];
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
  session_id?: string;
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
  action_regime_details?: StrategyRuntimeActionRegimeDetails | null;
  attribution_execution_details?: StrategyRuntimeAttributionExecutionDetails | null;
  control_optimizer_details?: StrategyRuntimeControlOptimizerDetails | null;
  control_action_deep_details?: StrategyRuntimeControlActionDeepDetails | null;
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

export type RobustnessAnalysisConfig = {
  cost_multipliers: number[];
  lookback_values?: number[] | null;
  threshold_values?: number[] | null;
  rebalance_values?: string[] | null;
  min_variants: number;
  max_variants: number;
  regime_vol_window: number;
  stress_shock_return: number;
  stress_vol_multiplier: number;
  base_constraints: Record<string, unknown>;
  base_cost_model: Record<string, number>;
};

export type RobustnessReport = {
  robustness_id: string;
  dataset_version: string;
  strategy_id: string;
  strategy_version: string;
  market: string;
  parent_task_id?: string | null;
  child_task_ids?: string[];
  summary_report_ref?: string | null;
  created_at: string;
  variants: RobustnessVariant[];
  summary: RobustnessSummary;
  table: Array<Record<string, number | string>>;
  regime_metrics: RegimeMetric[];
  stress_metrics: StressMetric[];
  worst_case_summary: WorstCaseSummary;
  outcome_summary?: StrategyRobustnessOutcomeSummary | null;
  result_details?: StrategyRobustnessResultDetails | null;
  base_strategy_spec: StrategySpec;
  base_strategy_validation: StrategyValidationResult;
  base_strategy_compilation: StrategyCompilationPlan;
  base_backtest_request: BacktestRequest;
  analysis_config: RobustnessAnalysisConfig;
};

export type SseEvent = {
  event_id?: string;
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
  factor_versions: FactorVersionRef[];
  runtime_summary?: StrategyRuntimeOutcomeSummary | null;
  runtime_diagnostics?: StrategyRuntimeDiagnosticsResult | null;
  action_regime_details?: StrategyRuntimeActionRegimeDetails | null;
  attribution_execution_details?: StrategyRuntimeAttributionExecutionDetails | null;
  control_optimizer_details?: StrategyRuntimeControlOptimizerDetails | null;
  control_action_deep_details?: StrategyRuntimeControlActionDeepDetails | null;
  metrics: Record<string, unknown>;
  created_at?: string | null;
  report_path?: string | null;
  report_missing?: boolean;
};

export type RestoreBacktestRequest = {
  run_id?: string | null;
  request: Record<string, unknown>;
  source: string;
  strategy_trace?: StrategyTraceArtifact | null;
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
