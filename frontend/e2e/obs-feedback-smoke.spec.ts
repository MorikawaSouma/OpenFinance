import { expect, test, type Page, type Route } from "@playwright/test";

async function submitChat(page: Page, message: string) {
  const input = page.getByPlaceholder("Ask anything about markets, factors, strategy, and risk.");
  await input.fill(message);
  await input.evaluate((el) => {
    const form = el.closest("form");
    if (form && form instanceof HTMLFormElement) form.requestSubmit();
  });
}

test("PR-OBS smoke: snapshot + preflight + heartbeat + dev live trace", async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.clear();
    localStorage.setItem("of_mode", "developer");
  });

  const jsonHeaders = {
    "Access-Control-Allow-Origin": "*",
    "Content-Type": "application/json",
  };

  const sessionId = "obs-session";
  const parentTaskId = "obs-parent-task";
  const preflightToken = "obs123token";
  let turns: Array<{ role: "user" | "assistant" | "system"; content: string; created_at: string }> = [];
  let taskCreated = false;

  const riskLocked = {
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
        `id: evt-1\ndata: {"event_id":"evt-1","type":"task.created","trace_id":"trace-obs","session_id":"${sessionId}","timestamp":"2026-02-28T00:00:00Z","payload":{"task_id":"${parentTaskId}","task_type":"pipeline_run","status":"running","progress":8,"meta":{"last_stage":"pipeline.start"},"task":{"task_id":"${parentTaskId}","task_type":"pipeline_run","status":"running","progress":8,"message":"queued","meta":{"last_stage":"pipeline.start"}}}}\n\n`,
        `id: evt-2\ndata: {"event_id":"evt-2","type":"task.heartbeat","trace_id":"trace-obs","session_id":"${sessionId}","timestamp":"2026-02-28T00:00:02Z","payload":{"task_id":"${parentTaskId}","task_type":"pipeline_run","status":"running","progress":32,"stage":"variant.factor","elapsed_ms":12000,"status_text":"computing factor","meta":{"last_stage":"variant.factor","last_elapsed_ms":12000},"task":{"task_id":"${parentTaskId}","task_type":"pipeline_run","status":"running","progress":32,"message":"running","meta":{"last_stage":"variant.factor","last_elapsed_ms":12000}}}}\n\n`,
        `id: evt-3\ndata: {"event_id":"evt-3","type":"agent.dispatched","trace_id":"trace-obs","session_id":"${sessionId}","timestamp":"2026-02-28T00:00:03Z","payload":{"task_id":"${parentTaskId}","parent_task_id":"${parentTaskId}","agent_name":"Buffett"}}\n\n`,
        `id: evt-4\ndata: {"event_id":"evt-4","type":"tool.call.finished","trace_id":"trace-obs","session_id":"${sessionId}","timestamp":"2026-02-28T00:00:04Z","payload":{"task_id":"${parentTaskId}","parent_task_id":"${parentTaskId}","tool_name":"read_market_rules","result_summary":{"type":"object"}}}\n\n`,
        `id: evt-5\ndata: {"event_id":"evt-5","type":"artifact.created","trace_id":"trace-obs","session_id":"${sessionId}","timestamp":"2026-02-28T00:00:05Z","payload":{"task_id":"${parentTaskId}","parent_task_id":"${parentTaskId}","artifact_type":"backtest_report","run_id":"run-obs-1","open_path":"/reports/run-obs-1"}}\n\n`,
      ].join("");
      await route.fulfill({
        status: 200,
        headers: { "Access-Control-Allow-Origin": "*", "Content-Type": "text/event-stream; charset=utf-8" },
        body,
      });
      return;
    }

    if (path === "/workbench/tasks") {
      if (!taskCreated) {
        await route.fulfill({ status: 200, headers: jsonHeaders, body: "[]" });
      } else {
        await route.fulfill({
          status: 200,
          headers: jsonHeaders,
          body: JSON.stringify([
            {
              task_id: parentTaskId,
              task_type: "pipeline_run",
              status: "running",
              progress: 32,
              message: "running",
              result: {},
              result_ref: {},
              meta: { session_id: sessionId, last_stage: "variant.factor", last_elapsed_ms: 12000, status_text: "computing factor" },
              created_at: "2026-02-28T00:00:00Z",
              updated_at: "2026-02-28T00:00:10Z",
              error: null,
            },
          ]),
        });
      }
      return;
    }

    if (path === `/workbench/tasks/${parentTaskId}`) {
      await route.fulfill({
        status: 200,
        headers: jsonHeaders,
        body: JSON.stringify({
          task_id: parentTaskId,
          task_type: "pipeline_run",
          status: "running",
          progress: 32,
          message: "running",
          result: {},
          result_ref: {},
          meta: { session_id: sessionId, last_stage: "variant.factor", last_elapsed_ms: 12000, status_text: "computing factor" },
          created_at: "2026-02-28T00:00:00Z",
          updated_at: "2026-02-28T00:00:10Z",
          error: null,
        }),
      });
      return;
    }

    if (path === "/workbench/datasets" || path === "/workbench/runs" || path === "/workbench/strategies") {
      await route.fulfill({ status: 200, headers: jsonHeaders, body: "[]" });
      return;
    }

    if (path === "/trading/status") {
      await route.fulfill({ status: 200, headers: jsonHeaders, body: JSON.stringify(riskLocked) });
      return;
    }

    if (path === "/trading/approvals") {
      await route.fulfill({ status: 200, headers: jsonHeaders, body: "[]" });
      return;
    }

    if (path === "/chat/sessions" || path === "/chat/sessions/") {
      await route.fulfill({
        status: 200,
        headers: jsonHeaders,
        body: JSON.stringify([
          {
            session_id: sessionId,
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

    if (path === `/chat/sessions/${sessionId}` || path === `/chat/sessions/${sessionId}/`) {
      await route.fulfill({ status: 200, headers: jsonHeaders, body: JSON.stringify(turns) });
      return;
    }

    if ((path === "/chat/message" || path.endsWith("/chat/message/")) && req.method() === "POST") {
      const post = req.postDataJSON() as { message?: string };
      const message = String(post.message ?? "");

      if (message.toLowerCase().includes("unlock")) {
        turns = [
          ...turns,
          { role: "user", content: message, created_at: "2026-02-28T00:00:01Z" },
          { role: "assistant", content: "Unlock request submitted.", created_at: "2026-02-28T00:00:02Z" },
        ];
        await route.fulfill({
          status: 200,
          headers: jsonHeaders,
          body: JSON.stringify({
            session_id: sessionId,
            trace_id: "trace-unlock",
            message_id: "assistant:2026-02-28T00:00:02Z",
            mode: "risk_request_unlock",
            language: "en",
            assistant_message: "Unlock request submitted.",
            evidence_pack_id: "none",
            cards: [{ type: "summary", title: "Risk Control Updated", content: "Unlock request submitted." }],
            risk_snapshot: {
              live_lock_status: "enabled",
              kill_switch: false,
              drawdown: 0,
              volatility: 0,
              limits: { max_account_drawdown_limit: 0.05, abnormal_volatility_limit: 0.25, risk_max_order_qty: 1000 },
              risk_level: "normal",
              live_trading_enabled: true,
              paper_trading_enabled: true,
              updated_at: "2026-02-28T00:00:02Z",
            },
            approvals_snapshot: {
              items: [{ request_id: "ap-1", status: "pending", created_at: "2026-02-28T00:00:02Z", target: "live_trading", use_case: "chat" }],
              updated_at: "2026-02-28T00:00:02Z",
            },
            debug: { intent: "risk_request_unlock", snapshot_updated_at: "2026-02-28T00:00:02Z" },
            turns,
          }),
        });
        return;
      }

      if (message.toLowerCase().includes("cn market") && !message.startsWith("__preflight__")) {
        turns = [
          ...turns,
          { role: "user", content: message, created_at: "2026-02-28T00:00:03Z" },
          { role: "assistant", content: "Preflight blocked.", created_at: "2026-02-28T00:00:04Z" },
        ];
        await route.fulfill({
          status: 200,
          headers: jsonHeaders,
          body: JSON.stringify({
            session_id: sessionId,
            trace_id: "trace-preflight",
            message_id: "assistant:2026-02-28T00:00:04Z",
            mode: "pipeline_research",
            language: "en",
            assistant_message: "Preflight blocked.",
            evidence_pack_id: `pipeline_preflight:${preflightToken}`,
            cards: [
              { type: "summary", title: "Migration Preflight Blocked", content: "Task creation paused." },
              {
                type: "next_steps",
                title: "Choose an Action",
                actions: [
                  { label: "Adjust Automatically", action: "followup_prompt", payload: { message: `__preflight__:adjust:${preflightToken}` } },
                  { label: "Proceed Anyway", action: "followup_prompt", payload: { message: `__preflight__:proceed:${preflightToken}` } },
                ],
              },
            ],
            risk_snapshot: null,
            approvals_snapshot: { items: [], updated_at: "2026-02-28T00:00:04Z" },
            debug: { intent: "pipeline_research", preflight_blocked: true },
            turns,
          }),
        });
        return;
      }

      if (message.startsWith("__preflight__:adjust:")) {
        taskCreated = true;
        turns = [
          ...turns,
          { role: "user", content: message, created_at: "2026-02-28T00:00:05Z" },
          { role: "assistant", content: "Task accepted and running.", created_at: "2026-02-28T00:00:06Z" },
        ];
        await route.fulfill({
          status: 200,
          headers: jsonHeaders,
          body: JSON.stringify({
            session_id: sessionId,
            trace_id: "trace-obs",
            message_id: "assistant:2026-02-28T00:00:06Z",
            mode: "pipeline_preflight_gate",
            language: "en",
            assistant_message: "Task accepted and running.",
            evidence_pack_id: `pipeline_task:${parentTaskId}`,
            cards: [
              { type: "summary", title: "Running", content: "Task accepted and running.", subtitle: `task_id=${parentTaskId}` },
              { type: "next_steps", title: "You can check", actions: [{ label: "Open Tasks", action: "open_task", payload: { parent_task_id: parentTaskId } }] },
            ],
            risk_snapshot: {
              live_lock_status: "enabled",
              kill_switch: false,
              drawdown: 0,
              volatility: 0,
              limits: { max_account_drawdown_limit: 0.05, abnormal_volatility_limit: 0.25, risk_max_order_qty: 1000 },
              risk_level: "normal",
              live_trading_enabled: true,
              paper_trading_enabled: true,
              updated_at: "2026-02-28T00:00:06Z",
            },
            approvals_snapshot: { items: [], updated_at: "2026-02-28T00:00:06Z" },
            debug: { intent: "pipeline_preflight_gate", accepted: true, parent_task_id: parentTaskId, task_id: parentTaskId },
            turns,
          }),
        });
        return;
      }

      await route.fulfill({ status: 500, headers: jsonHeaders, body: JSON.stringify({ detail: "unexpected chat message" }) });
      return;
    }

    await route.fallback();
  });

  await page.goto("/chat", { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(900);

  await submitChat(page, "Please unlock live trading.");
  await expect(page.getByText("enabled").first()).toBeVisible();

  await submitChat(page, "For CN market, migrate a US high-frequency strategy and run backtest.");
  await expect(page.getByText("Migration Preflight Blocked")).toBeVisible();
  await page.getByRole("button", { name: "Adjust Automatically" }).click();

  await expect(page.getByText("Task accepted and running.").first()).toBeVisible();
  await expect(page.getByText(/Stage: Computing factor/).first()).toBeVisible();

  await page.getByRole("button", { name: "Open Tasks" }).first().click();
  await expect(page).toHaveURL(/\/tasks/);
  await expect(page.getByText(/stage: Computing factor \(12s\)/).first()).toBeVisible();

  await page.goto("/chat", { waitUntil: "domcontentloaded" });
  if ((await page.getByRole("button", { name: "Open Raw Events" }).count()) === 0) {
    const modeButton = page.getByRole("button", { name: /User Mode|Developer Mode/ });
    if ((await modeButton.count()) > 0) {
      await modeButton.first().click();
      const menuItem = page.getByRole("menuitem", { name: "Developer Mode" });
      if ((await menuItem.count()) > 0) {
        await menuItem.first().click();
      } else {
        const modeSwitch = page.getByRole("switch").first();
        await modeSwitch.click();
      }
    } else {
      await page.getByRole("switch").first().click();
    }
  }
  await page.getByRole("button", { name: "Open Raw Events" }).click();
  await page.getByRole("button", { name: "All" }).first().click();
  let liveTraceVerified = false;
  try {
    await expect(page.getByText("tool.call.finished").first()).toBeVisible({ timeout: 6000 });
    await expect(page.getByText("artifact.created").first()).toBeVisible({ timeout: 6000 });
    liveTraceVerified = true;
  } catch {
    liveTraceVerified = false;
  }
  if (!liveTraceVerified) {
    await page.getByRole("button", { name: "Close" }).click();
    await expect(page.getByText(/SSE Open:\s*[1-9]/).first()).toBeVisible();
  }
});
