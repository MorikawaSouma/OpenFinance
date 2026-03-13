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

async function mockCommon(page: Page) {
  const headers = {
    "Access-Control-Allow-Origin": "*",
    "Content-Type": "application/json",
  };
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
        body: "id: evt-1\ndata: {\"event_id\":\"evt-1\",\"type\":\"audit.trace\",\"trace_id\":\"trace-sse\",\"session_id\":\"sse\",\"timestamp\":\"2026-02-28T00:00:00Z\",\"payload\":{\"heartbeat\":true}}\n\n",
      });
      return;
    }
    if (path === "/workbench/datasets") return route.fulfill({ status: 200, headers, body: "[]" });
    if (path === "/workbench/runs") return route.fulfill({ status: 200, headers, body: "[]" });
    if (path === "/workbench/strategies") return route.fulfill({ status: 200, headers, body: "[]" });
    if (path === "/trading/approvals") return route.fulfill({ status: 200, headers, body: "[]" });
    if (path === "/trading/status") return route.fulfill({ status: 200, headers, body: JSON.stringify(riskPayload()) });
    await route.fallback();
  });
}

async function sendAndWait(page: Page, prompt: string, visibleText: string) {
  const input = page.getByPlaceholder("Ask anything about markets, factors, strategy, and risk.");
  const send = page.getByRole("button", { name: "Send", exact: true });
  let ok = false;
  for (let i = 0; i < 3; i += 1) {
    await input.fill(prompt);
    await expect(input).toHaveValue(prompt);
    await send.click();
    try {
      await expect(page.getByText(visibleText)).toBeVisible({ timeout: 3500 });
      ok = true;
      break;
    } catch {
      await page.waitForTimeout(250);
    }
  }
  expect(ok).toBe(true);
}

test("compare run remains consistent across chat/tasks/pipeline navigation", async ({ page }) => {
  const parentTaskId = "task-mm-parent";
  const childRows = [
    {
      task_id: "task-mm-child-us",
      parent_task_id: parentTaskId,
      task_type: "multi_market.market_run",
      status: "done",
      progress: 100,
      message: "done: US",
      result: {},
      result_ref: { run_id: "run-us", report_id: "run-us", open_path: "/reports/run-us" },
      meta: { market: "US" },
      created_at: "2026-02-28T00:01:00Z",
      updated_at: "2026-02-28T00:02:00Z",
      error: null,
    },
    {
      task_id: "task-mm-child-jp",
      parent_task_id: parentTaskId,
      task_type: "multi_market.market_run",
      status: "done",
      progress: 100,
      message: "done: JP",
      result: {},
      result_ref: { run_id: "run-jp", report_id: "run-jp", open_path: "/reports/run-jp" },
      meta: { market: "JP" },
      created_at: "2026-02-28T00:01:10Z",
      updated_at: "2026-02-28T00:02:10Z",
      error: null,
    },
  ];

  await mockCommon(page);
  const headers = {
    "Access-Control-Allow-Origin": "*",
    "Content-Type": "application/json",
  };

  await page.route("**/*", async (route: Route) => {
    const req = route.request();
    const path = new URL(req.url()).pathname;
    if (path === "/chat/sessions" || path === "/chat/sessions/") {
      await route.fulfill({
        status: 200,
        headers,
        body: JSON.stringify([
          {
            session_id: "session-mm",
            last_message: "seed",
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
    if (path === "/chat/sessions/session-mm" || path === "/chat/sessions/session-mm/") {
      await route.fulfill({ status: 200, headers, body: JSON.stringify([]) });
      return;
    }
    if (path === "/workbench/tasks") {
      const parent = {
        task_id: parentTaskId,
        task_type: "multi_market.compare",
        status: "done",
        progress: 100,
        message: "2/2 market runs completed",
        result: { compare_id: "mmc_case", baseline_market: "US", row_count: 2 },
        result_ref: { report_id: "mmc_case", open_path: "/reports?compare_id=mmc_case", compare_path: "/reports" },
        meta: { markets: ["US", "JP"] },
        created_at: "2026-02-28T00:00:00Z",
        updated_at: "2026-02-28T00:03:00Z",
        error: null,
      };
      await route.fulfill({ status: 200, headers, body: JSON.stringify([parent, ...childRows]) });
      return;
    }
    if ((path === "/chat/message" || path.endsWith("/chat/message/")) && req.method() === "POST") {
      await route.fulfill({
        status: 200,
        headers,
        body: JSON.stringify({
          session_id: "session-mm",
          trace_id: "trace-mm",
          message_id: "assistant:2026-02-28T00:00:01Z",
          mode: "multi_market_compare_report",
          language: "en",
          assistant_message: "US vs JP comparable backtests completed.",
          evidence_pack_id: "multi-market:mmc_case",
          cards: [
            {
              card_id: "assistant:2026-02-28T00:00:01Z:summary:0",
              type: "summary",
              title: "Comparison Summary",
              content: "US vs JP comparable backtests completed.",
            },
            {
              card_id: "assistant:2026-02-28T00:00:01Z:comparison_table:1",
              type: "comparison_table",
              title: "Comparable Backtest Table",
              table: [
                { metric: "Sharpe", us: "0.72", jp: "0.64", difference: "+0.08" },
                { metric: "MDD", us: "12.00%", jp: "9.00%", difference: "+3.00%" },
              ],
            },
            {
              card_id: "assistant:2026-02-28T00:00:01Z:next_steps:2",
              type: "next_steps",
              title: "Next Steps",
              actions: [{ label: "Open Tasks", action: "open_task", payload: { parent_task_id: parentTaskId } }],
            },
          ],
          debug: { parent_task_id: parentTaskId, message_id: "assistant:2026-02-28T00:00:01Z" },
          turns: [
            { role: "user", content: "Run comparable US vs JP report", created_at: "2026-02-28T00:00:00Z" },
            { role: "assistant", content: "US vs JP comparable backtests completed.", created_at: "2026-02-28T00:00:01Z" },
          ],
        }),
      });
      return;
    }
    await route.fallback();
  });

  await page.goto("/chat", { waitUntil: "domcontentloaded" });
  await sendAndWait(page, "Run comparable US vs JP report", "Comparison Summary");
  await expect(page.getByText("Comparison Summary")).toHaveCount(1);
  await expect(page.getByText("Comparable Backtest Table")).toHaveCount(1);
  await page.getByRole("button", { name: "Open Tasks", exact: true }).click();

  await expect(page).toHaveURL(/\/tasks/);
  await expect(page.getByText("multi_market.compare")).toBeVisible();
  await expect(page.getByText("2/2 market runs completed").first()).toBeVisible();

  await page.goto("/pipeline", { waitUntil: "domcontentloaded" });
  await page.goto("/chat", { waitUntil: "domcontentloaded" });
  await expect(page.getByText("Comparison Summary")).toHaveCount(1);
  await expect(page.getByText("Comparable Backtest Table")).toHaveCount(1);
});

test("failed compare returns error card instead of blank output", async ({ page }) => {
  await mockCommon(page);
  const headers = {
    "Access-Control-Allow-Origin": "*",
    "Content-Type": "application/json",
  };

  await page.route("**/*", async (route: Route) => {
    const req = route.request();
    const path = new URL(req.url()).pathname;
    if (path === "/chat/sessions" || path === "/chat/sessions/") {
      await route.fulfill({
        status: 200,
        headers,
        body: JSON.stringify([
          {
            session_id: "session-mm-fail",
            last_message: "seed",
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
    if (path === "/chat/sessions/session-mm-fail" || path === "/chat/sessions/session-mm-fail/") {
      await route.fulfill({ status: 200, headers, body: JSON.stringify([]) });
      return;
    }
    if (path === "/workbench/tasks") {
      await route.fulfill({
        status: 200,
        headers,
        body: JSON.stringify([
          {
            task_id: "task-fail-parent",
            task_type: "multi_market.compare",
            status: "error",
            progress: 100,
            message: "multi-market compare failed",
            result: {},
            result_ref: {},
            meta: { markets: ["US", "JP"] },
            created_at: "2026-02-28T00:00:00Z",
            updated_at: "2026-02-28T00:01:00Z",
            error: "forced task failure",
          },
        ]),
      });
      return;
    }
    if ((path === "/chat/message" || path.endsWith("/chat/message/")) && req.method() === "POST") {
      await route.fulfill({
        status: 200,
        headers,
        body: JSON.stringify({
          session_id: "session-mm-fail",
          trace_id: "trace-mm-fail",
          message_id: "assistant:2026-02-28T00:00:02Z",
          mode: "multi_market_compare_report",
          language: "en",
          assistant_message: "Multi-market comparable backtest failed. Error was recorded; check Tasks and retry.",
          evidence_pack_id: "multi-market:failed",
          cards: [
            {
              card_id: "assistant:2026-02-28T00:00:02Z:summary:0",
              type: "summary",
              title: "Task Failed",
              content: "Multi-market comparable backtest failed. Error was recorded; check Tasks and retry.",
              subtitle: "forced task failure",
            },
            {
              card_id: "assistant:2026-02-28T00:00:02Z:next_steps:1",
              type: "next_steps",
              title: "Suggested Actions",
              actions: [{ label: "Open Tasks", action: "open_task", payload: { parent_task_id: "task-fail-parent" } }],
            },
          ],
          debug: { parent_task_id: "task-fail-parent", error: "forced task failure" },
          turns: [
            { role: "user", content: "Run comparable US vs JP report", created_at: "2026-02-28T00:00:00Z" },
            {
              role: "assistant",
              content: "Multi-market comparable backtest failed. Error was recorded; check Tasks and retry.",
              created_at: "2026-02-28T00:00:02Z",
            },
          ],
        }),
      });
      return;
    }
    await route.fallback();
  });

  await page.goto("/chat", { waitUntil: "domcontentloaded" });
  await sendAndWait(page, "Run comparable US vs JP report", "Task Failed");
  await expect(page.getByText("Task Failed")).toBeVisible();
  await expect(page.getByText("forced task failure")).toBeVisible();
  await page.getByRole("button", { name: "Open Tasks", exact: true }).click();
  await expect(page.getByText("multi_market.compare")).toBeVisible();
  await expect(page.getByText("error").first()).toBeVisible();
});
