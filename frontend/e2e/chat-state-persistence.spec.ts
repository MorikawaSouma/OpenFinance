import { expect, test, type Page, type Route } from "@playwright/test";

async function mockChatPersistenceApis(page: Page) {
  const sessionId = "session-persist";
  let turns: Array<{ role: "user" | "assistant" | "system"; content: string; created_at: string }> = [];
  const jsonHeaders = {
    "Access-Control-Allow-Origin": "*",
    "Content-Type": "application/json",
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
      await route.fulfill({
        status: 200,
        headers: {
          "Access-Control-Allow-Origin": "*",
          "Content-Type": "text/event-stream; charset=utf-8",
        },
        body: "data: {\"type\":\"audit.trace\",\"trace_id\":\"persist\",\"session_id\":\"persist\",\"timestamp\":\"2026-02-27T00:00:00Z\",\"payload\":{\"heartbeat\":true}}\n\n",
      });
      return;
    }

    if (path === "/workbench/tasks") return route.fulfill({ status: 200, headers: jsonHeaders, body: "[]" });
    if (path === "/workbench/datasets") return route.fulfill({ status: 200, headers: jsonHeaders, body: "[]" });
    if (path === "/workbench/runs") return route.fulfill({ status: 200, headers: jsonHeaders, body: "[]" });
    if (path === "/workbench/strategies") return route.fulfill({ status: 200, headers: jsonHeaders, body: "[]" });
    if (path === "/trading/approvals") return route.fulfill({ status: 200, headers: jsonHeaders, body: "[]" });
    if (path === "/trading/status") {
      return route.fulfill({
        status: 200,
        headers: jsonHeaders,
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
    }

    if (path === "/chat/sessions" || path === "/chat/sessions/") {
      return route.fulfill({
        status: 200,
        headers: jsonHeaders,
        body: JSON.stringify([
          {
            session_id: sessionId,
            last_message: turns.length > 0 ? turns[turns.length - 1].content : "persist seed",
            updated_at: "2026-02-27T00:00:00Z",
            last_plan_id: "",
            last_run_id: "",
            last_report_id: "",
            last_dataset_version: "",
            recent_run_ids: [],
          },
        ]),
      });
    }

    if (path === `/chat/sessions/${sessionId}` || path === `/chat/sessions/${sessionId}/`) {
      return route.fulfill({
        status: 200,
        headers: jsonHeaders,
        body: JSON.stringify(turns),
      });
    }

    if ((path === "/chat/message" || path.endsWith("/chat/message/")) && req.method() === "POST") {
      const payload = req.postDataJSON() as { message?: string; include_debug?: boolean };
      const user = String(payload.message ?? "compare");
      turns = [
        { role: "user", content: user, created_at: "2026-02-27T00:00:00Z" },
        { role: "assistant", content: "US vs JP compare done", created_at: "2026-02-27T00:00:01Z" },
      ];
      return route.fulfill({
        status: 200,
        headers: jsonHeaders,
        body: JSON.stringify({
          session_id: sessionId,
          trace_id: "trace-persist",
          mode: "market_compare",
          language: "en",
          assistant_message: "US vs JP compare done",
          evidence_pack_id: "pack-us|pack-jp",
          cards: [
            { type: "summary", title: "Comparison Summary", content: "US is more sensitive while JP is relatively stable." },
            {
              type: "comparison_table",
              title: "Comparison Table",
              table: [
                { metric: "Drawdown", us: "18.00%", jp: "12.00%", difference: "US is more sensitive." },
                { metric: "Volatility", us: "25.00%", jp: "19.00%", difference: "US is more sensitive." },
              ],
            },
          ],
          debug: payload.include_debug ? { intent: "market_compare" } : {},
          turns,
        }),
      });
    }

    return route.fallback();
  });
}

test("chat cards persist across Chat-Pipeline-Chat and page reload", async ({ page }) => {
  await mockChatPersistenceApis(page);

  await page.goto("/chat", { waitUntil: "domcontentloaded" });
  await expect(page.getByRole("heading", { name: "Research Workspace", exact: true })).toBeVisible();
  const modeSwitch = page.getByRole("switch").first();
  await expect(modeSwitch).toBeVisible();
  await modeSwitch.click();
  await modeSwitch.click();

  const input = page.getByPlaceholder("Ask anything about markets, factors, strategy, and risk.");
  const send = page.getByRole("button", { name: "Send", exact: true });
  let sent = false;
  for (let i = 0; i < 3; i += 1) {
    await input.fill("Compare US vs JP under the same framework.");
    await expect(input).toHaveValue("Compare US vs JP under the same framework.");
    await send.click();
    try {
      await expect(page.getByText("Comparison Table")).toBeVisible({ timeout: 3500 });
      sent = true;
      break;
    } catch {
      await page.waitForTimeout(300);
    }
  }
  expect(sent).toBe(true);
  await expect(page.getByText("Drawdown")).toBeVisible();

  await page.goto("/pipeline", { waitUntil: "domcontentloaded" });
  await expect(page).toHaveURL(/\/pipeline$/);

  await page.goto("/chat", { waitUntil: "domcontentloaded" });
  await expect(page.getByText("Comparison Table")).toBeVisible();
  await expect(page.getByText("Drawdown")).toBeVisible();

  await page.reload({ waitUntil: "domcontentloaded" });
  await expect(page.getByText("Comparison Table")).toBeVisible();
  await expect(page.getByText("Drawdown")).toBeVisible();
});
