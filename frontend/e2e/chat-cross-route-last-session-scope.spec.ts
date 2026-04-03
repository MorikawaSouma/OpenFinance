import { expect, test, type Page, type Route } from "@playwright/test";

type SessionId = "session-a" | "session-c";

type Turn = {
  role: "user" | "assistant" | "system";
  content: string;
  created_at: string;
};

type TaskFixture = {
  task_id: string;
  task_type: string;
  status: string;
  progress: number;
  message: string;
  created_at: string;
  updated_at: string;
  meta: Record<string, unknown>;
  result?: Record<string, unknown>;
  result_ref?: Record<string, unknown>;
  error?: string | null;
};

const JSON_HEADERS = {
  "Access-Control-Allow-Origin": "*",
  "Content-Type": "application/json",
};

function installInitScript(
  page: Page,
  options: {
    initialLastSessionId: string;
  }
) {
  return page.addInitScript((payload) => {
    const bootstrapped = sessionStorage.getItem("__of_cross_route_bootstrapped") === "1";
    if (!bootstrapped) {
      localStorage.clear();
      localStorage.setItem(
        "research_context_v1",
        JSON.stringify({
          state: {
            lastSessionId: payload.initialLastSessionId,
            lastTraceId: null,
            lastPlanId: null,
            restoredSessionId: null,
            restoredTraceId: null,
            lastRestoredAt: null,
          },
          version: 1,
        })
      );
      sessionStorage.setItem("__of_cross_route_bootstrapped", "1");
    }
  }, options);
}

function seedTurns(sessionId: string): Turn[] {
  return [
    { role: "user", content: `${sessionId} seeded question`, created_at: "2026-03-23T00:00:00.000Z" },
    { role: "assistant", content: `${sessionId} seeded answer`, created_at: "2026-03-23T00:00:01.000Z" },
  ];
}

function buildStrategyCompilation(suffix: "a" | "c") {
  return {
    schema_version: "strategy_compilation.v1",
    strategy_id: `strategy-${suffix}`,
    strategy_version: `strategy-${suffix}`,
    market: "US",
    executable_object: "BacktestRequest",
    compile_ready: true,
    validation_status: "ok",
    decision_status: "aligned",
    selected_candidate: "RiskBudgetAllocator",
    summary: `scope-${suffix} compiles into BacktestRequest with explicit runtime inputs`,
    bindings: [
      {
        output_path: "request.strategy_version",
        value: `strategy-${suffix}`,
        source_kind: "strategy_spec",
        source_path: "strategy_version",
        note: "Durable strategy version used for runtime request.",
      },
      {
        output_path: "request.execution_model",
        value: "next_open",
        source_kind: "runtime_request",
        source_path: "execution_model",
        note: "Execution model is a compile-time runtime input.",
      },
    ],
    overlays: [],
    evidence_refs: [],
    compilation_profile: {
      schema_version: "strategy_compilation_profile.v1",
      profile_id: "backtest_request.simulation.v1",
      executable_object: "BacktestRequest",
      summary: `9 user-configurable path(s), 1 environment-bound path(s), 4 runtime-derived path(s), and 0 validation-required override path(s) feed scope-${suffix} BacktestRequest.`,
      input_policies: [
        {
          output_path: "constraints.strategy_family",
          classification: "user_configurable",
          configured_by: "strategy_spec",
          validated_by: "strategy_validation",
          source_kind: "strategy_spec",
          source_path: "strategy_family",
          rationale: `scope-${suffix} family remains durable strategy semantics`,
        },
        {
          output_path: "request.execution_model",
          classification: "environment_bound",
          configured_by: "system_environment",
          validated_by: "not_applicable",
          source_kind: "runtime_request",
          source_path: "execution_model",
          rationale: "Execution model remains runtime-owned.",
        },
      ],
      override_policies: [],
    },
    compilation_policy: {
      schema_version: "strategy_compilation_policy.v1",
      checked_object: "strategy_compilation_profile",
      rule_surface_schema_version: "strategy_compilation_policy_rules.v1",
      rule_surface_id: "strategy_compilation.backtest.v1",
      market: "US",
      environment: "backtest",
      status: "allowed",
      compile_ready: true,
      summary: `2 allowed, 0 warning, and 0 blocked compile-policy check(s) for market=US environment=backtest.`,
      warning_count: 0,
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
      ],
    },
  };
}

function buildPipelineResponse(suffix: "a" | "c") {
  return {
    trace_id: `trace-pipeline-${suffix}`,
    plan_id: `plan-${suffix}`,
    run_id: `run-${suffix}`,
    strategy_spec: {
      schema_version: "strategy_spec.v1",
      strategy_id: `strategy-${suffix}`,
      strategy_version: `strategy-${suffix}`,
      plan_id: `plan-${suffix}`,
      experiment_id: `experiment-${suffix}`,
      market: "US",
      strategy_family: "trend",
      rebalance: "weekly",
      lookback_days: 20,
      signal_threshold: 0,
      position_sizing: "risk_budget",
      risk_budget: "vol_target_10pct",
      max_position: 0.12,
      stop_loss: 0.06,
      leverage_limit: 1,
      factor_weights: {},
      constraints: {},
      circuit_breaker: { enabled: true, rule: { type: "drawdown", threshold: 0.1, cool_down_days: 5 } },
      failure_regimes: ["high_volatility_regime"],
      rationale: `scope-${suffix} strategy`,
      evidence_refs: [],
      simulation_only: true,
    },
    strategy_decision: null,
    strategy_validation: {
      schema_version: "strategy_validation.v1",
      validated_object: "strategy_spec",
      strategy_id: `strategy-${suffix}`,
      strategy_version: `strategy-${suffix}`,
      market: "US",
      status: "ok",
      compile_ready: true,
      decision_status: "aligned",
      selected_candidate: "RiskBudgetAllocator",
      next_output: "BacktestRequest",
      summary: "Strategy validation passed and is compile-ready for BacktestRequest.",
      checks: [],
      evidence_refs: [],
    },
    strategy_compilation: buildStrategyCompilation(suffix),
    research_plan: {
      objectives: [`scope-${suffix}-objective`],
      candidate_strategy_families: ["trend"],
      value: { hypotheses: [`scope-${suffix}-value`] },
      macro: { hypotheses: [`scope-${suffix}-macro`] },
      stats: { hypotheses: [`scope-${suffix}-stats`] },
      behavior: { hypotheses: [`scope-${suffix}-behavior`] },
    },
    steps: [
      { name: "plan.compose", status: "done" },
      { name: "evidence.pack", status: "done" },
    ],
    comparison_table: [],
  };
}

function createTaskFixtures(): TaskFixture[] {
  return [
    {
      task_id: "root-a-1",
      task_type: "research.scope",
      status: "running",
      progress: 25,
      message: "scope-a root task",
      created_at: "2026-03-23T00:00:00Z",
      updated_at: "2026-03-23T00:00:05Z",
      meta: { session_id: "session-a" },
      result: {},
      result_ref: {},
    },
    {
      task_id: "mm-a-1",
      task_type: "multi_market.compare",
      status: "running",
      progress: 21,
      message: "scope-a multi market task",
      created_at: "2026-03-23T00:01:00Z",
      updated_at: "2026-03-23T00:01:05Z",
      meta: { session_id: "session-a" },
      result: {},
      result_ref: {},
    },
    {
      task_id: "rb-a-1",
      task_type: "robustness.run",
      status: "running",
      progress: 31,
      message: "scope-a robustness task",
      created_at: "2026-03-23T00:02:00Z",
      updated_at: "2026-03-23T00:02:05Z",
      meta: { session_id: "session-a" },
      result: {},
      result_ref: {},
    },
    {
      task_id: "factor-a-1",
      task_type: "factor.run",
      status: "running",
      progress: 41,
      message: "scope-a factor task",
      created_at: "2026-03-23T00:03:00Z",
      updated_at: "2026-03-23T00:03:05Z",
      meta: { session_id: "session-a" },
      result: {},
      result_ref: {},
    },
    {
      task_id: "factor-mm-a",
      task_type: "factor.multi_market_compare",
      status: "running",
      progress: 51,
      message: "scope-a factor compare task",
      created_at: "2026-03-23T00:03:10Z",
      updated_at: "2026-03-23T00:03:15Z",
      meta: { session_id: "session-a" },
      result: {},
      result_ref: {},
    },
    {
      task_id: "pipe-a-1",
      task_type: "pipeline_run",
      status: "done",
      progress: 100,
      message: "scope-a pipeline task",
      created_at: "2026-03-23T00:04:00Z",
      updated_at: "2026-03-23T00:04:05Z",
      meta: { session_id: "session-a" },
      result: { pipeline_response: buildPipelineResponse("a") },
      result_ref: { run_id: "run-a", open_path: "/reports/run-a" },
    },
    {
      task_id: "root-c-1",
      task_type: "research.scope",
      status: "running",
      progress: 26,
      message: "scope-c root task",
      created_at: "2026-03-23T00:10:00Z",
      updated_at: "2026-03-23T00:10:05Z",
      meta: { session_id: "session-c" },
      result: {},
      result_ref: {},
    },
    {
      task_id: "mm-c-1",
      task_type: "multi_market.compare",
      status: "running",
      progress: 22,
      message: "scope-c multi market task",
      created_at: "2026-03-23T00:11:00Z",
      updated_at: "2026-03-23T00:11:05Z",
      meta: { session_id: "session-c" },
      result: {},
      result_ref: {},
    },
    {
      task_id: "rb-c-1",
      task_type: "robustness.run",
      status: "running",
      progress: 32,
      message: "scope-c robustness task",
      created_at: "2026-03-23T00:12:00Z",
      updated_at: "2026-03-23T00:12:05Z",
      meta: { session_id: "session-c" },
      result: {},
      result_ref: {},
    },
    {
      task_id: "factor-c-1",
      task_type: "factor.run",
      status: "running",
      progress: 42,
      message: "scope-c factor task",
      created_at: "2026-03-23T00:13:00Z",
      updated_at: "2026-03-23T00:13:05Z",
      meta: { session_id: "session-c" },
      result: {},
      result_ref: {},
    },
    {
      task_id: "factor-mm-c",
      task_type: "factor.multi_market_compare",
      status: "running",
      progress: 52,
      message: "scope-c factor compare task",
      created_at: "2026-03-23T00:13:10Z",
      updated_at: "2026-03-23T00:13:15Z",
      meta: { session_id: "session-c" },
      result: {},
      result_ref: {},
    },
    {
      task_id: "pipe-c-1",
      task_type: "pipeline_run",
      status: "done",
      progress: 100,
      message: "scope-c pipeline task",
      created_at: "2026-03-23T00:14:00Z",
      updated_at: "2026-03-23T00:14:05Z",
      meta: { session_id: "session-c" },
      result: { pipeline_response: buildPipelineResponse("c") },
      result_ref: { run_id: "run-c", open_path: "/reports/run-c" },
    },
  ];
}

async function mockCrossRouteApis(page: Page) {
  const turnsBySession = new Map<string, Turn[]>([
    ["session-a", seedTurns("session-a")],
    ["session-b", seedTurns("session-b")],
    ["session-c", seedTurns("session-c")],
  ]);
  const tasks = createTaskFixtures();
  const taskById = new Map(tasks.map((task) => [task.task_id, task]));

  await page.route("**/*", async (route: Route) => {
    const req = route.request();
    const url = new URL(req.url());
    const path = url.pathname;

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
        headers: {
          "Access-Control-Allow-Origin": "*",
          "Content-Type": "text/event-stream; charset=utf-8",
        },
        body: 'data: {"event_id":"scope-audit","type":"audit.trace","trace_id":"trace-scope","session_id":"sse","timestamp":"2026-03-23T00:00:00Z","payload":{"heartbeat":true}}\n\n',
      });
      return;
    }

    if (path === "/workbench/tasks") {
      await route.fulfill({ status: 200, headers: JSON_HEADERS, body: JSON.stringify(tasks) });
      return;
    }

    if (path.startsWith("/workbench/tasks/")) {
      const taskId = path.replace("/workbench/tasks/", "");
      const task = taskById.get(taskId);
      if (!task) {
        await route.fulfill({ status: 404, headers: JSON_HEADERS, body: JSON.stringify({ detail: "not found" }) });
        return;
      }
      await route.fulfill({ status: 200, headers: JSON_HEADERS, body: JSON.stringify(task) });
      return;
    }

    if (path === "/workbench/datasets") {
      await route.fulfill({
        status: 200,
        headers: JSON_HEADERS,
        body: JSON.stringify([
          {
            dataset_version: "dataset-v1",
            market: "US",
            date_range: { start: "2024-01-01", end: "2024-03-31" },
          },
        ]),
      });
      return;
    }

    if (path === "/workbench/runs") {
      await route.fulfill({
        status: 200,
        headers: JSON_HEADERS,
        body: JSON.stringify([
          {
            run_id: "run-a",
            market: "US",
            start: "2024-01-01",
            end: "2024-03-31",
            sharpe: 1.1,
            max_drawdown: 0.12,
            audit_trace_id: "trace-run-a",
          },
          {
            run_id: "run-c",
            market: "JP",
            start: "2024-01-01",
            end: "2024-03-31",
            sharpe: 1.4,
            max_drawdown: 0.08,
            audit_trace_id: "trace-run-c",
          },
        ]),
      });
      return;
    }

    if (path === "/workbench/strategies") {
      await route.fulfill({ status: 200, headers: JSON_HEADERS, body: "[]" });
      return;
    }

    if (path === "/workbench/factors") {
      await route.fulfill({
        status: 200,
        headers: JSON_HEADERS,
        body: JSON.stringify([
          {
            factor_id: "intraday_formula",
            version: "factor-v1",
            created_at: "2026-03-23T00:00:00Z",
            summary: "scope factor",
          },
        ]),
      });
      return;
    }

    if (path === "/workbench/factors/factor-v1") {
      await route.fulfill({
        status: 200,
        headers: JSON_HEADERS,
        body: JSON.stringify({
          factor_id: "intraday_formula",
          version: "factor-v1",
          spec: {
            factor_id: "intraday_formula",
            expected_horizon: "swing",
            failure_conditions: ["high_volatility"],
            cost_sensitivity: { level: "medium", rationale: "verification" },
          },
          report: {
            ic_mean: 0.11,
            rank_ic_mean: 0.09,
            t_stat: 2.1,
            coverage: 0.95,
            missing_rate: 0.01,
          },
        }),
      });
      return;
    }

    if (path === "/trading/approvals") {
      await route.fulfill({ status: 200, headers: JSON_HEADERS, body: "[]" });
      return;
    }

    if (path === "/trading/status") {
      await route.fulfill({
        status: 200,
        headers: JSON_HEADERS,
        body: JSON.stringify({
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
        }),
      });
      return;
    }

    if (path === "/chat/sessions" || path === "/chat/sessions/") {
      await route.fulfill({
        status: 200,
        headers: JSON_HEADERS,
        body: JSON.stringify([
          {
            session_id: "session-a",
            last_message: "session-a latest",
            updated_at: "2026-03-23T00:00:01Z",
            last_plan_id: "",
            last_run_id: "",
            last_report_id: "",
            last_dataset_version: "",
            recent_run_ids: [],
          },
          {
            session_id: "session-b",
            last_message: "session-b latest",
            updated_at: "2026-03-23T00:00:02Z",
            last_plan_id: "",
            last_run_id: "",
            last_report_id: "",
            last_dataset_version: "",
            recent_run_ids: [],
          },
          {
            session_id: "session-c",
            last_message: "session-c latest",
            updated_at: "2026-03-23T00:00:03Z",
            last_plan_id: "",
            last_run_id: "",
            last_report_id: "",
            last_dataset_version: "",
            recent_run_ids: [],
          },
        ]),
      });
      return;
    }

    if (path.startsWith("/chat/sessions/")) {
      const sessionId = path.replace("/chat/sessions/", "");
      await route.fulfill({
        status: 200,
        headers: JSON_HEADERS,
        body: JSON.stringify(turnsBySession.get(sessionId) ?? []),
      });
      return;
    }

    await route.fallback();
  });
}

async function readLastSessionId(page: Page) {
  return page.evaluate(() => {
    const raw = window.localStorage.getItem("research_context_v1");
    if (!raw) return null;
    const parsed = JSON.parse(raw) as { state?: { lastSessionId?: string | null } };
    return parsed.state?.lastSessionId ?? null;
  });
}

async function verifyCrossRouteScope(page: Page, expectedSession: SessionId) {
  const suffix = expectedSession.endsWith("a") ? "a" : "c";
  const oppositeSuffix = suffix === "a" ? "c" : "a";

  await page.goto("/reports", { waitUntil: "domcontentloaded" });
  await expect.poll(() => readLastSessionId(page)).toBe(expectedSession);
  await expect(page.getByRole("heading", { name: "Reports", exact: true })).toBeVisible();
  await expect(page.getByRole("link", { name: `run-${suffix}` })).toBeVisible();
  await expect(page.getByText(/Running:\s*10/)).toBeVisible();
  await page.getByRole("tab", { name: /^Multi-Market$/ }).click();
  await expect(page.getByText(new RegExp(`Task mm-${suffix}-1`))).toBeVisible();
  await expect(page.getByText(new RegExp(`Task mm-${oppositeSuffix}-1`))).toHaveCount(0);
  await page.getByRole("tab", { name: /^Robustness$/ }).click();
  await expect(page.getByText(new RegExp(`Task rb-${suffix}-1`))).toBeVisible();

  await page.goto("/tasks", { waitUntil: "domcontentloaded" });
  await expect.poll(() => readLastSessionId(page)).toBe(expectedSession);
  await expect(page.getByText(`scope-${suffix} root task`)).toBeVisible();
  await expect(page.getByText(`scope-${oppositeSuffix} root task`)).toHaveCount(0);

  await page.goto("/pipeline", { waitUntil: "domcontentloaded" });
  await expect.poll(() => readLastSessionId(page)).toBe(expectedSession);
  await expect(page.getByText(`plan_id: plan-${suffix}`)).toBeVisible();
  await expect(page.getByRole("link", { name: "Open Run Report" })).toHaveAttribute("href", `/reports/run-${suffix}`);

  await page.goto("/factors", { waitUntil: "domcontentloaded" });
  await expect.poll(() => readLastSessionId(page)).toBe(expectedSession);
  await expect(page.getByText(`task_id=factor-${suffix}-1`, { exact: false })).toBeVisible();
  await expect(page.getByText(`task_id=factor-${oppositeSuffix}-1`, { exact: false })).toHaveCount(0);
}

async function switchChatSessionToC(page: Page) {
  await page.goto("/chat", { waitUntil: "domcontentloaded" });
  await expect(page.getByText("session-a seeded answer")).toBeVisible();
  await page.getByRole("button", { name: /session-c latest/i }).click();
  await expect(page.getByText("session-c seeded answer")).toBeVisible();
}

test("cross-route pages follow the new chat session through research continuity ownership", async ({ page }) => {
  await installInitScript(page, {
    initialLastSessionId: "session-a",
  });
  await mockCrossRouteApis(page);

  await switchChatSessionToC(page);
  await expect.poll(() => readLastSessionId(page)).toBe("session-c");
  await verifyCrossRouteScope(page, "session-c");
});
