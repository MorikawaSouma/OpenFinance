import { expect, test, type Page, type Route } from "@playwright/test";

type Turn = { role: "user" | "assistant" | "system"; content: string; created_at: string };

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

async function submitChat(page: Page, message: string) {
  const input = page.getByPlaceholder("Ask anything about markets, factors, strategy, and risk.");
  await input.fill(message);
  await expect(input).toHaveValue(message);
  await input.evaluate((el) => {
    const form = el.closest("form");
    if (form && form instanceof HTMLFormElement) form.requestSubmit();
  });
}

async function mockCore(page: Page, opts: { failPipeline?: boolean } = {}) {
  const jsonHeaders = {
    "Access-Control-Allow-Origin": "*",
    "Content-Type": "application/json",
  };
  const parentTaskId = opts.failPipeline ? "task-jp-parent-fail" : "task-jp-parent";
  const childTaskId = opts.failPipeline ? "task-jp-child-fail" : "task-jp-child-1";
  let turns: Turn[] = [];
  let submittedPipeline = false;
  let taskTick = 0;
  let chatPostCount = 0;

  const runningParent = {
    task_id: parentTaskId,
    task_type: "pipeline_run",
    status: "running",
    progress: 42,
    message: "1/3 variants completed",
    result: {},
    result_ref: {},
    meta: { session_id: "session-jp", trace_id: "trace-jp" },
    created_at: "2026-02-28T00:00:00Z",
    updated_at: "2026-02-28T00:01:00Z",
    error: null,
  };
  const runningChild = {
    task_id: childTaskId,
    parent_task_id: parentTaskId,
    task_type: "backtest_variant",
    status: "running",
    progress: 72,
    message: "variant.backtest: v1",
    result: {},
    result_ref: {},
    meta: { session_id: "session-jp", variant_id: "v1" },
    created_at: "2026-02-28T00:00:10Z",
    updated_at: "2026-02-28T00:01:10Z",
    error: null,
  };
  const doneParent = {
    ...runningParent,
    status: "done",
    progress: 100,
    message: "3/3 variants completed",
    result: { run_id: "run-jp-1" },
    result_ref: { run_id: "run-jp-1", report_id: "run-jp-1", open_path: "/reports/run-jp-1", compare_path: "/reports" },
    updated_at: "2026-02-28T00:03:00Z",
  };
  const doneChild = {
    ...runningChild,
    status: "done",
    progress: 100,
    message: "done: v1",
    result_ref: { run_id: "run-jp-1", report_id: "run-jp-1", open_path: "/reports/run-jp-1" },
    updated_at: "2026-02-28T00:03:00Z",
  };
  const errorParent = {
    ...runningParent,
    status: "error",
    progress: 100,
    message: "pipeline failed",
    error: "forced pipeline variant failure",
    updated_at: "2026-02-28T00:03:00Z",
  };
  const errorChild = {
    ...runningChild,
    status: "error",
    progress: 100,
    message: "error: v1",
    error: "forced pipeline variant failure",
    updated_at: "2026-02-28T00:03:00Z",
  };

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
      const body = [
        `data: {"type":"task.created","event_id":"evt-1","trace_id":"trace-jp","session_id":"session-jp","timestamp":"2026-02-28T00:00:00Z","payload":{"task_id":"${parentTaskId}","task_type":"pipeline_run","status":"queued","progress":0}}\n\n`,
        `data: {"type":"task.created","event_id":"evt-2","trace_id":"trace-jp","session_id":"session-jp","timestamp":"2026-02-28T00:00:01Z","payload":{"task_id":"${childTaskId}","parent_task_id":"${parentTaskId}","task_type":"backtest_variant","status":"running","progress":15}}\n\n`,
        `data: {"type":"task.progress","event_id":"evt-3","trace_id":"trace-jp","session_id":"session-jp","timestamp":"2026-02-28T00:00:02Z","payload":{"task_id":"${parentTaskId}","status":"running","progress":42}}\n\n`,
        opts.failPipeline
          ? `data: {"type":"task.error","event_id":"evt-4","trace_id":"trace-jp","session_id":"session-jp","timestamp":"2026-02-28T00:00:03Z","payload":{"task_id":"${parentTaskId}","status":"error","progress":100,"error":"forced pipeline variant failure"}}\n\n`
          : `data: {"type":"task.done","event_id":"evt-4","trace_id":"trace-jp","session_id":"session-jp","timestamp":"2026-02-28T00:00:03Z","payload":{"task_id":"${parentTaskId}","status":"done","progress":100,"result_ref":{"run_id":"run-jp-1","open_path":"/reports/run-jp-1"}}}\n\n`,
      ].join("");
      await route.fulfill({
        status: 200,
        headers: { "Access-Control-Allow-Origin": "*", "Content-Type": "text/event-stream; charset=utf-8" },
        body,
      });
      return;
    }
    if (path === "/workbench/datasets") return route.fulfill({ status: 200, headers: jsonHeaders, body: "[]" });
    if (path === "/workbench/runs") return route.fulfill({ status: 200, headers: jsonHeaders, body: "[]" });
    if (path === "/workbench/strategies") return route.fulfill({ status: 200, headers: jsonHeaders, body: "[]" });
    if (path === "/trading/approvals") return route.fulfill({ status: 200, headers: jsonHeaders, body: "[]" });
    if (path === "/trading/status") return route.fulfill({ status: 200, headers: jsonHeaders, body: JSON.stringify(riskPayload()) });
    if (path === "/workbench/runs/run-jp-1") {
      await route.fulfill({
        status: 200,
        headers: jsonHeaders,
        body: JSON.stringify({
          run_id: "run-jp-1",
          dataset_version: "v1",
          strategy_version: "s1",
          factor_versions: [],
          audit_trace_id: "trace-jp",
          created_at: "2026-02-28T00:00:00Z",
          metrics: { sharpe: 0.8, max_drawdown: 0.08, total_return: 0.15 },
          charts: [],
          diagnostics: {},
          evidence_refs: [],
          equity_curve: [],
          orders: [],
          trades: [],
          positions: [],
          cost_breakdown: {},
        }),
      });
      return;
    }
    if (path === "/workbench/tasks") {
      if (!submittedPipeline) {
        await route.fulfill({ status: 200, headers: jsonHeaders, body: "[]" });
        return;
      }
      taskTick += 1;
      if (opts.failPipeline) {
        await route.fulfill({ status: 200, headers: jsonHeaders, body: JSON.stringify([errorParent, errorChild]) });
        return;
      }
      if (taskTick <= 1) {
        await route.fulfill({ status: 200, headers: jsonHeaders, body: JSON.stringify([runningParent, runningChild]) });
        return;
      }
      await route.fulfill({ status: 200, headers: jsonHeaders, body: JSON.stringify([doneParent, doneChild]) });
      return;
    }
    if (path === `/workbench/tasks/${parentTaskId}`) {
      if (!submittedPipeline) {
        await route.fulfill({ status: 404, headers: jsonHeaders, body: JSON.stringify({ detail: "task not found" }) });
        return;
      }
      const body = opts.failPipeline ? errorParent : taskTick <= 1 ? runningParent : doneParent;
      await route.fulfill({ status: 200, headers: jsonHeaders, body: JSON.stringify(body) });
      return;
    }
    if (path === `/workbench/tasks/${childTaskId}`) {
      const body = opts.failPipeline ? errorChild : taskTick <= 1 ? runningChild : doneChild;
      await route.fulfill({ status: 200, headers: jsonHeaders, body: JSON.stringify(body) });
      return;
    }
    if (path === "/chat/sessions" || path === "/chat/sessions/") {
      await route.fulfill({
        status: 200,
        headers: jsonHeaders,
        body: JSON.stringify([
          {
            session_id: "session-jp",
            last_message: turns.length > 0 ? turns[turns.length - 1].content : "seed",
            updated_at: "2026-02-28T00:00:00Z",
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
    if (path === "/chat/sessions/session-jp" || path === "/chat/sessions/session-jp/") {
      await route.fulfill({ status: 200, headers: jsonHeaders, body: JSON.stringify(turns) });
      return;
    }
    if ((path === "/chat/message" || path.endsWith("/chat/message/")) && req.method() === "POST") {
      chatPostCount += 1;
      const payload = req.postDataJSON() as { message?: string };
      const message = String(payload.message ?? "");
      const normalized = message.toLowerCase();
      if (normalized.includes("nikkei") || message.includes("日经")) {
        turns = [
          { role: "user", content: message, created_at: "2026-02-28T00:00:00Z" },
          { role: "assistant", content: "JP market quick summary:\n- Volatility elevated", created_at: "2026-02-28T00:00:01Z" },
        ];
        await route.fulfill({
          status: 200,
          headers: jsonHeaders,
          body: JSON.stringify({
            session_id: "session-jp",
            trace_id: "trace-gi",
            message_id: "assistant:2026-02-28T00:00:01Z",
            mode: "general_info_query",
            language: "en",
            assistant_message: "JP market quick summary:\n- Volatility elevated",
            evidence_pack_id: "pack-jp",
            cards: [{ type: "summary", title: "Summary", content: "JP market quick summary:\n- Volatility elevated" }],
            debug: { intent: "general_info_query" },
            turns,
          }),
        });
        return;
      }

      submittedPipeline = true;
      turns = [
        ...turns,
        { role: "user", content: message, created_at: "2026-02-28T00:00:02Z" },
        {
          role: "assistant",
          content: "Task #taskjp00 accepted and running. Open Tasks for progress.",
          created_at: "2026-02-28T00:00:03Z",
        },
      ];
      await route.fulfill({
        status: 200,
        headers: jsonHeaders,
        body: JSON.stringify({
          session_id: "session-jp",
          trace_id: "trace-jp",
          message_id: "assistant:2026-02-28T00:00:03Z",
          mode: "pipeline_research",
          language: "en",
          assistant_message: "Task #taskjp00 accepted and running. Open Tasks for progress.",
          evidence_pack_id: `pipeline_task:${parentTaskId}`,
          cards: [
            {
              card_id: "assistant:2026-02-28T00:00:03Z:summary:0",
              type: "summary",
              title: "Running",
              content: "Task #taskjp00 accepted and running. Open Tasks for progress.",
              subtitle: `task_id=${parentTaskId}`,
            },
            {
              card_id: "assistant:2026-02-28T00:00:03Z:next_steps:1",
              type: "next_steps",
              title: "You can check",
              actions: [{ label: "Open Tasks", action: "open_task", payload: { parent_task_id: parentTaskId } }],
            },
          ],
          debug: { intent: "pipeline_research", accepted: true, parent_task_id: parentTaskId, task_id: parentTaskId },
          turns,
        }),
      });
      return;
    }

    await route.fallback();
  });

  return {
    getChatPostCount: () => chatPostCount,
  };
}

test("PR-RUN-PROGRESS-01 case1 chat->tasks->chat remains recoverable", async ({ page }) => {
  const mock = await mockCore(page, { failPipeline: false });
  await page.addInitScript(() => localStorage.clear());
  await page.goto("/chat", { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(1200);

  await submitChat(page, "Nikkei recent performance?");
  await expect.poll(() => mock.getChatPostCount()).toBeGreaterThan(0);
  await expect(page.getByText("Summary", { exact: true }).first()).toBeVisible();

  await submitChat(page, "Based on current JP market, propose a low drawdown strategy and run backtest.");
  await expect(page.getByRole("button", { name: "Open Tasks", exact: true }).first()).toBeVisible();
  await page.getByRole("button", { name: "Open Tasks", exact: true }).first().click();

  await expect(page).toHaveURL(/\/tasks/);
  await expect(page.getByText("pipeline_run")).toBeVisible();
  await expect(page.getByText("backtest_variant")).toBeVisible();

  await page.goto("/pipeline", { waitUntil: "domcontentloaded" });
  await page.goto("/chat", { waitUntil: "domcontentloaded" });
  await expect(page.getByText("Task #taskjp00 accepted and running. Open Tasks for progress.").first()).toBeVisible();

  await page.reload({ waitUntil: "domcontentloaded" });
  await expect(page.getByText("Task #taskjp00 accepted and running. Open Tasks for progress.").first()).toBeVisible();
});

test("PR-RUN-PROGRESS-01 case2 variant failure surfaces error in tasks/chat", async ({ page }) => {
  const mock = await mockCore(page, { failPipeline: true });
  await page.addInitScript(() => localStorage.clear());
  await page.goto("/chat", { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(1200);

  await submitChat(page, "Based on current JP market, propose a low drawdown strategy and run backtest.");
  await expect.poll(() => mock.getChatPostCount()).toBeGreaterThan(0);

  await expect(page.getByRole("button", { name: "Open Tasks", exact: true }).first()).toBeVisible();
  await expect(page.getByText("forced pipeline variant failure")).toBeVisible();
  await page.getByRole("button", { name: "Open Tasks", exact: true }).first().click();
  await expect(page.getByText("pipeline failed")).toBeVisible();
  await expect(page.getByText("error").first()).toBeVisible();
});
