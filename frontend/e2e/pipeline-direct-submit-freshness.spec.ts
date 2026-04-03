import { expect, test, type Page, type Route } from "@playwright/test";

function riskPayload() {
  return {
    mode: "paper",
    kill_switch_enabled: false,
    live_trading_enabled: false,
    paper_trading_enabled: false,
    risk_max_order_qty: 1000,
    live_approval_state: "locked",
    paper_approval_state: "requested",
    pending_approval_count: 0,
    current_drawdown: 0,
    current_volatility: 0,
    max_account_drawdown_limit: 0.05,
    abnormal_volatility_limit: 0.25,
    recent_risk_events: [],
  };
}

function buildStrategyCompilation() {
  return {
    schema_version: "strategy_compilation.v1",
    strategy_id: "plan_strategy",
    strategy_version: "strategy-p2b3-1",
    market: "JP",
    executable_object: "BacktestRequest",
    compile_ready: true,
    validation_status: "ok",
    decision_status: "aligned",
    selected_candidate: "RiskBudgetAllocator",
    summary: "StrategySpec compiles cleanly into BacktestRequest with explicit runtime inputs.",
    bindings: [
      {
        output_path: "request.strategy_version",
        value: "strategy-p2b3-1",
        source_kind: "strategy_spec",
        source_path: "strategy_version",
        note: "Durable strategy version carried into request.",
      },
      {
        output_path: "request.execution_model",
        value: "next_open",
        source_kind: "runtime_request",
        source_path: "execution_model",
        note: "Execution model is injected at compile time.",
      },
    ],
    overlays: [
      {
        output_path: "request.execution_model",
        final_value: "next_open",
        source_kind: "runtime_request",
        source_path: "execution_model",
        overridden_source_kind: "default",
        overridden_source_path: "execution_model",
        overridden_value: "next_open",
        rationale: "Pipeline request pins execution model explicitly.",
      },
    ],
    evidence_refs: ["plan:plan-p2b3-pipeline", "factor_version:factor-p2b3-1"],
    compilation_profile: {
      schema_version: "strategy_compilation_profile.v1",
      profile_id: "backtest_request.simulation.v1",
      executable_object: "BacktestRequest",
      summary: "10 user-configurable path(s), 1 environment-bound path(s), 4 runtime-derived path(s), and 1 validation-required override path(s) feed this BacktestRequest.",
      input_policies: [
        {
          output_path: "constraints.strategy_family",
          classification: "user_configurable",
          configured_by: "strategy_spec",
          validated_by: "strategy_validation",
          source_kind: "strategy_spec",
          source_path: "strategy_family",
          rationale: "Strategy family remains durable strategy semantics.",
        },
        {
          output_path: "request.execution_model",
          classification: "environment_bound",
          configured_by: "system_environment",
          validated_by: "not_applicable",
          source_kind: "runtime_request",
          source_path: "execution_model",
          rationale: "Execution model remains an executable/runtime concern.",
        },
      ],
      override_policies: [
        {
          output_path: "request.execution_model",
          classification: "environment_bound",
          configured_by: "system_environment",
          source_kind: "runtime_request",
          source_path: "execution_model",
          requires_additional_validation: false,
          rationale: "Execution model is environment-owned.",
        },
      ],
    },
    compilation_policy: {
      schema_version: "strategy_compilation_policy.v1",
      checked_object: "strategy_compilation_profile",
      rule_surface_schema_version: "strategy_compilation_policy_rules.v1",
      rule_surface_id: "strategy_compilation.backtest.v1",
      market: "JP",
      environment: "backtest",
      status: "allowed_with_warning",
      compile_ready: true,
      summary: "2 allowed, 1 warning, and 0 blocked compile-policy check(s) for market=JP environment=backtest.",
      warning_count: 1,
      blocked_count: 0,
      checks: [
        {
          rule_id: "runtime.execution_model_supported",
          code: "execution_model_supported",
          output_path: "request.execution_model",
          classification: "environment_bound",
          configured_by: "system_environment",
          outcome: "allowed",
          checked_by: "backtest_runtime",
          fact_source: "backtest_runner.supported_execution_models",
          requires_additional_validation: false,
          detail: "Execution model next_open is supported by the current BacktestRunner.",
        },
        {
          rule_id: "migration.trading_session_coverage_gap",
          code: "trading_session_coverage_gap",
          output_path: "environment.run_time_utc",
          classification: "environment_bound",
          configured_by: "system_environment",
          outcome: "allowed_with_warning",
          checked_by: "migration_checker",
          fact_source: "migration_checker.warning_codes",
          requires_additional_validation: true,
          detail: "Configured execution time 16:00 UTC does not map to a tradable session in JP. Orders may queue or miss intended timing.",
        },
      ],
    },
  };
}

function buildPipelineResponse() {
  return {
    trace_id: "trace-p2b3-pipeline",
    question: "Why is Nikkei volatility rising recently?",
    market: "JP",
    plan_id: "plan-p2b3-pipeline",
    evidence_pack_id: "evidence-p2b3-pipeline",
    evidence_sources: [],
    factor_version: "factor-p2b3-1",
    strategy_version: "strategy-p2b3-1",
    dataset_version: "dataset-p2b3-1",
    run_id: "run-p2b3-1",
    backtest_metrics: { sharpe: 0.81, max_drawdown: 0.09 },
    strategy_spec: {
      schema_version: "strategy_spec.v1",
      strategy_id: "plan_strategy",
      strategy_version: "strategy-p2b3-1",
      plan_id: "plan-p2b3-pipeline",
      experiment_id: "variant-p2b3-1",
      market: "JP",
      strategy_family: "trend",
      rebalance: "weekly",
      lookback_days: 20,
      signal_threshold: 0,
      position_sizing: "risk_budget",
      risk_budget: "vol_target_10pct",
      max_position: 0.12,
      stop_loss: 0.06,
      leverage_limit: 1,
      factor_weights: { momentum_1d: 1 },
      constraints: {},
      circuit_breaker: { enabled: true, rule: { type: "drawdown", threshold: 0.1, cool_down_days: 5 } },
      failure_regimes: ["high_volatility_regime"],
      rationale: "Risk-budget allocator for JP volatility regime.",
      evidence_refs: ["plan:plan-p2b3-pipeline", "factor_version:factor-p2b3-1"],
      simulation_only: true,
    },
    strategy_decision: {
      schema_version: "strategy_decision.v1",
      llm_mode: "mock",
      selected: {
        name: "RiskBudgetAllocator",
        spec: {
          strategy_family: "trend",
          rebalance: "weekly",
          lookback_days: 20,
          signal_threshold: 0,
          position_sizing: "risk_budget",
          risk_budget: "vol_target_10pct",
          max_position: 0.12,
          leverage_limit: 1,
          auto_round_lot: true,
          run_time_utc: "14:00",
        },
        rationale: "Risk-budget allocator for JP volatility regime.",
        tradeoff_summary: "Higher model complexity in exchange for better downside control.",
      },
      candidates: [
        {
          name: "RiskBudgetAllocator",
          spec: {
            strategy_family: "trend",
            rebalance: "weekly",
            lookback_days: 20,
            signal_threshold: 0,
            position_sizing: "risk_budget",
            risk_budget: "vol_target_10pct",
            max_position: 0.12,
            leverage_limit: 1,
            auto_round_lot: true,
            run_time_utc: "14:00",
          },
          pros: ["Better drawdown control"],
          cons: ["Needs covariance estimate"],
          risks: ["Model complexity"],
          expected_failure_regimes: ["high_volatility_regime"],
          cost_profile: "moderate",
          why_not_selected: "",
        },
      ],
    },
    strategy_validation: {
      schema_version: "strategy_validation.v1",
      validated_object: "strategy_spec",
      strategy_id: "plan_strategy",
      strategy_version: "strategy-p2b3-1",
      market: "JP",
      status: "ok",
      compile_ready: true,
      decision_status: "aligned",
      selected_candidate: "RiskBudgetAllocator",
      next_output: "BacktestRequest",
      summary: "Strategy validation passed and is compile-ready for BacktestRequest.",
      checks: [
        { check_id: "spec_fields", status: "ok", detail: "trend/risk_budget/weekly fits current simulation profile for market=JP." },
        { check_id: "decision_alignment", status: "ok", detail: "Selected proposal RiskBudgetAllocator matches the durable StrategySpec fields." },
        { check_id: "evidence_linkage", status: "ok", detail: "Linked to 2 evidence references." },
        { check_id: "compile_boundary", status: "ok", detail: "StrategySpec is ready to compile into BacktestRequest; runtime task state remains outside validation." },
      ],
      evidence_refs: ["plan:plan-p2b3-pipeline", "factor_version:factor-p2b3-1"],
    },
    strategy_compilation: buildStrategyCompilation(),
    risk_explanation: "Paper-trading only route.",
    research_plan: {
      plan_id: "plan-p2b3-pipeline",
      question: "Why is Nikkei volatility rising recently?",
      market: "JP",
      markets: ["JP"],
      objectives: ["low drawdown", "stable factor exposures"],
      constraints: {},
      evidence_queries: ["nikkei volatility drivers"],
      candidate_factors: [],
      candidate_strategy_families: ["trend"],
      experiment_matrix: [],
      risk_checks: ["max drawdown <= 10%"],
      output_format: ["report", "steps"],
      seed: 42,
      value: { hypotheses: ["cheap cyclicals revert"], evidence_queries: [], evaluation_actions: [], risks: [] },
      macro: { hypotheses: ["yen weakness spills into exporters"], evidence_queries: [], evaluation_actions: [], risks: [] },
      stats: { hypotheses: ["volatility regime shift"], evidence_queries: [], evaluation_actions: [], risks: [] },
      behavior: { hypotheses: ["risk aversion clustering"], evidence_queries: [], evaluation_actions: [], risks: [] },
    },
    experiments: [],
    comparison_table: [],
    interpretation: "JP risk premium is elevated.",
    agent_outputs: [],
    reasoning_steps: [],
    preflight_warnings: [],
    preflight_actions: [],
    llm_mode: "mock",
    steps: [
      { name: "plan.compose", status: "done", summary: "plan ready", artifacts: [] },
      { name: "dataset.prepare", status: "done", summary: "dataset ready", artifacts: [] },
      { name: "backtest.run", status: "done", summary: "run ready", artifacts: [] },
    ],
  };
}

async function mockPipelineDirectApis(page: Page) {
  const jsonHeaders = {
    "Access-Control-Allow-Origin": "*",
    "Content-Type": "application/json",
  };
  const taskId = "task-p2b3-pipeline";
  let getTaskCalls = 0;

  await page.route("**/*", async (route: Route) => {
    const req = route.request();
    const path = new URL(req.url()).pathname;

    if (req.method() === "OPTIONS") {
      await route.fulfill({
        status: 204,
        headers: {
          "Access-Control-Allow-Origin": "*",
          "Access-Control-Allow-Headers": "content-type",
          "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
        },
      });
      return;
    }

    if (path === "/events/stream") {
      await route.fulfill({
        status: 200,
        headers: { "Access-Control-Allow-Origin": "*", "Content-Type": "text/event-stream; charset=utf-8" },
        body: 'data: {"event_id":"evt-p2b3-open","type":"audit.trace","trace_id":"trace-p2b3-pipeline","session_id":"pipeline","timestamp":"2026-03-23T00:00:00Z","payload":{"heartbeat":true}}\n\n',
      });
      return;
    }

    if (path === "/workbench/datasets") {
      await route.fulfill({ status: 200, headers: jsonHeaders, body: "[]" });
      return;
    }

    if (path === "/workbench/runs") {
      await route.fulfill({ status: 200, headers: jsonHeaders, body: "[]" });
      return;
    }

    if (path === "/workbench/strategies") {
      await route.fulfill({ status: 200, headers: jsonHeaders, body: "[]" });
      return;
    }

    if (path === "/trading/status") {
      await route.fulfill({ status: 200, headers: jsonHeaders, body: JSON.stringify(riskPayload()) });
      return;
    }

    if (path === "/trading/approvals") {
      await route.fulfill({ status: 200, headers: jsonHeaders, body: "[]" });
      return;
    }

    if (path === "/plan" && req.method() === "POST") {
      await route.fulfill({
        status: 200,
        headers: jsonHeaders,
        body: JSON.stringify({
          trace_id: "trace-p2b3-pipeline",
          plan_id: "plan-p2b3-pipeline",
          plan: buildPipelineResponse().research_plan,
          evidence_pack_id: "evidence-p2b3-pipeline",
          preflight_warnings: [],
          llm_mode: "mock",
        }),
      });
      return;
    }

    if (path === "/run/submit" && req.method() === "POST") {
      await route.fulfill({
        status: 200,
        headers: jsonHeaders,
        body: JSON.stringify({
          task_id: taskId,
          task_type: "pipeline_run",
          status: "running",
          progress: 8,
          message: "queued",
          result: {},
          result_ref: {},
          meta: { session_id: "pipeline", trace_id: "trace-p2b3-pipeline", market: "JP" },
          created_at: "2026-03-23T00:00:00Z",
          updated_at: "2026-03-23T00:00:00Z",
          error: null,
        }),
      });
      return;
    }

    if (path === `/workbench/tasks/${taskId}`) {
      getTaskCalls += 1;
      const body =
        getTaskCalls < 2
          ? {
              task_id: taskId,
              task_type: "pipeline_run",
              status: "running",
              progress: 44,
              message: "1/3 variants completed",
              result: {},
              result_ref: {},
              meta: { session_id: "pipeline", trace_id: "trace-p2b3-pipeline", last_stage: "variant.backtest" },
              created_at: "2026-03-23T00:00:00Z",
              updated_at: "2026-03-23T00:00:02Z",
              error: null,
            }
          : {
              task_id: taskId,
              task_type: "pipeline_run",
              status: "done",
              progress: 100,
              message: "pipeline complete",
              result: {
                run_id: "run-p2b3-1",
                strategy_version: "strategy-p2b3-1",
                pipeline_response: buildPipelineResponse(),
              },
              result_ref: {
                run_id: "run-p2b3-1",
                report_id: "run-p2b3-1",
                open_path: "/reports/run-p2b3-1",
              },
              meta: { session_id: "pipeline", trace_id: "trace-p2b3-pipeline", last_stage: "pipeline.done" },
              created_at: "2026-03-23T00:00:00Z",
              updated_at: "2026-03-23T00:00:04Z",
              error: null,
            };
      await route.fulfill({ status: 200, headers: jsonHeaders, body: JSON.stringify(body) });
      return;
    }

    await route.fallback();
  });

  return {
    getTaskCalls: () => getTaskCalls,
  };
}

test("pipeline direct submit keeps progress and completion under domain-owned reconcile", async ({ page }) => {
  const stats = await mockPipelineDirectApis(page);
  await page.addInitScript(() => localStorage.clear());

  await page.goto("/pipeline", { waitUntil: "domcontentloaded" });
  await expect(page.getByText("No pipeline run yet")).toBeVisible();

  await page.getByRole("button", { name: "Run End-to-End" }).click();
  await expect(page.getByText("Executing...")).toBeVisible();
  await expect.poll(() => stats.getTaskCalls()).toBeGreaterThan(1);

  await expect(page.getByRole("link", { name: "Open Run Report" })).toHaveAttribute("href", "/reports/run-p2b3-1");
  await expect(page.getByText("Plan Snapshot")).toBeVisible();
  await expect(page.getByText("plan.compose")).toBeVisible();
});
