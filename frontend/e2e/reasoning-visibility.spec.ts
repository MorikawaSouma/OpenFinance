import { expect, test, type Route } from "@playwright/test";

test("PR-RV smoke: reasoning steps stream, skip step, parse fallback", async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.clear();
    localStorage.setItem("of_mode", "developer");
  });

  const jsonHeaders = {
    "Access-Control-Allow-Origin": "*",
    "Content-Type": "application/json",
  };
  const sessionId = "rv-session";
  const traceId = "trace-rv";

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
        `id: rv-1\ndata: {"event_id":"rv-1","type":"reasoning.step.created","trace_id":"${traceId}","session_id":"${sessionId}","timestamp":"2026-02-28T00:00:01Z","payload":{"step":{"trace_id":"${traceId}","session_id":"${sessionId}","task_id":"task-rv","agent_name":"Kahneman","step_idx":1,"step_type":"hypothesis","title":"Hypothesis Draft","summary":"Initial hypothesis drafted.","evidence_refs":[],"created_at":"2026-02-28T00:00:01Z","prompt_hash":"sha1:a1"}}}\n\n`,
        `id: rv-2\ndata: {"event_id":"rv-2","type":"reasoning.step.created","trace_id":"${traceId}","session_id":"${sessionId}","timestamp":"2026-02-28T00:00:02Z","payload":{"step":{"trace_id":"${traceId}","session_id":"${sessionId}","task_id":"task-rv","agent_name":"Kahneman","step_idx":2,"step_type":"evidence_use","title":"Evidence Used","summary":"Selected top evidence.","evidence_refs":[{"source_id":"src-1","title":"Macro Note","ts":"2026-02-27T00:00:00Z"}],"created_at":"2026-02-28T00:00:02Z","prompt_hash":"sha1:a1"}}}\n\n`,
        `id: rv-3\ndata: {"event_id":"rv-3","type":"reasoning.step.created","trace_id":"${traceId}","session_id":"${sessionId}","timestamp":"2026-02-28T00:00:03Z","payload":{"step":{"trace_id":"${traceId}","session_id":"${sessionId}","task_id":"task-rv","agent_name":"Kahneman","step_idx":3,"step_type":"counterevidence_use","title":"Counterevidence Check","summary":"Counter evidence challenged the base thesis.","evidence_refs":[{"source_id":"src-2","title":"Counter Case","ts":"2026-02-27T12:00:00Z"}],"created_at":"2026-02-28T00:00:03Z","prompt_hash":"sha1:a1"}}}\n\n`,
        `id: rv-4\ndata: {"event_id":"rv-4","type":"reasoning.trace.final","trace_id":"${traceId}","session_id":"${sessionId}","timestamp":"2026-02-28T00:00:04Z","payload":{"agent_name":"Kahneman","steps_count":3,"has_parse_error":false}}\n\n`,
        `id: rv-5\ndata: {"event_id":"rv-5","type":"reasoning.step.created","trace_id":"trace-rv-skip","session_id":"${sessionId}","timestamp":"2026-02-28T00:00:05Z","payload":{"step":{"trace_id":"trace-rv-skip","session_id":"${sessionId}","task_id":"task-rv-2","agent_name":"Simons","step_idx":3,"step_type":"warning","title":"Counterevidence Skip","summary":"no strong counterevidence found","evidence_refs":[],"created_at":"2026-02-28T00:00:05Z","prompt_hash":"sha1:b2"}}}\n\n`,
        `id: rv-6\ndata: {"event_id":"rv-6","type":"reasoning.step.created","trace_id":"trace-rv-parse","session_id":"${sessionId}","timestamp":"2026-02-28T00:00:06Z","payload":{"step":{"trace_id":"trace-rv-parse","session_id":"${sessionId}","task_id":"task-rv-3","agent_name":"Buffett","step_idx":4,"step_type":"warning","title":"Parse Fallback","summary":"Fallback reasoning steps used.","parse_error":"forced_parse_error","evidence_refs":[],"created_at":"2026-02-28T00:00:06Z","prompt_hash":"sha1:c3"}}}\n\n`,
      ].join("");
      await route.fulfill({
        status: 200,
        headers: { "Access-Control-Allow-Origin": "*", "Content-Type": "text/event-stream; charset=utf-8" },
        body,
      });
      return;
    }

    if (path === "/workbench/tasks" || path === "/workbench/datasets" || path === "/workbench/runs" || path === "/workbench/strategies") {
      await route.fulfill({ status: 200, headers: jsonHeaders, body: "[]" });
      return;
    }
    if (path.startsWith("/workbench/tasks/")) {
      await route.fulfill({ status: 200, headers: jsonHeaders, body: JSON.stringify({ task_id: "task-rv", task_type: "pipeline_run", status: "running", progress: 20, message: "running", result: {}, result_ref: {}, meta: {} }) });
      return;
    }
    if (path === "/trading/status") {
      await route.fulfill({
        status: 200,
        headers: jsonHeaders,
        body: JSON.stringify({
          mode: "paper",
          kill_switch_enabled: false,
          live_trading_enabled: false,
          paper_trading_enabled: false,
          risk_max_order_qty: 1000,
          live_approval_state: "locked",
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
    if (path === `/chat/sessions/${sessionId}` || path === `/chat/sessions/${sessionId}/`) {
      await route.fulfill({ status: 200, headers: jsonHeaders, body: "[]" });
      return;
    }
    if ((path === "/chat/message" || path.endsWith("/chat/message/")) && req.method() === "POST") {
      await route.fulfill({
        status: 200,
        headers: jsonHeaders,
        body: JSON.stringify({
          session_id: sessionId,
          trace_id: traceId,
          message_id: "assistant:rv",
          mode: "general_info_query",
          language: "en",
          assistant_message: "ok",
          evidence_pack_id: "ep-rv",
          cards: [],
          debug: {},
          turns: [],
        }),
      });
      return;
    }

    await route.fallback();
  });

  await page.goto("/chat", { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(900);
  if ((await page.getByRole("button", { name: "Open Raw Events" }).count()) === 0) {
    await page.getByRole("button", { name: /User Mode|Developer Mode/ }).click();
    await page.getByRole("menuitem", { name: "Developer Mode" }).click();
  }
  await page.getByRole("button", { name: "Open Raw Events" }).click();
  await page.getByRole("button", { name: "Reasoning Steps" }).click();

  await expect(page.getByText("counterevidence_use").first()).toBeVisible();
  await page.screenshot({ path: "e2e/artifacts/pr-rv-01-stream.png", fullPage: true });

  await expect(page.getByText("no strong counterevidence found").first()).toBeVisible();
  await page.screenshot({ path: "e2e/artifacts/pr-rv-02-skip.png", fullPage: true });

  await expect(page.getByText("parse_error=forced_parse_error").first()).toBeVisible();
  await page.screenshot({ path: "e2e/artifacts/pr-rv-03-parse-fallback.png", fullPage: true });
});
