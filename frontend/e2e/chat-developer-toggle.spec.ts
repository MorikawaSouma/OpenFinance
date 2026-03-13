import { expect, test, type Page, type Route } from "@playwright/test";

async function mockChatCoreApis(page: Page) {
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
        body: "data: {\"type\":\"audit.trace\",\"trace_id\":\"toggle\",\"session_id\":\"s1\",\"timestamp\":\"2026-02-27T00:00:00Z\",\"payload\":{\"heartbeat\":true}}\n\n",
      });
      return;
    }

    if (path === "/workbench/tasks") return route.fulfill({ status: 200, headers: jsonHeaders, body: "[]" });
    if (path === "/workbench/datasets") return route.fulfill({ status: 200, headers: jsonHeaders, body: "[]" });
    if (path === "/workbench/runs") return route.fulfill({ status: 200, headers: jsonHeaders, body: "[]" });
    if (path === "/workbench/strategies") return route.fulfill({ status: 200, headers: jsonHeaders, body: "[]" });
    if (path === "/trading/approvals") return route.fulfill({ status: 200, headers: jsonHeaders, body: "[]" });

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
        headers: jsonHeaders,
        body: JSON.stringify([
          {
            session_id: "session-toggle",
            last_message: "seed",
            updated_at: "2026-02-27T00:00:00Z",
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

    if (path === "/chat/sessions/session-toggle" || path === "/chat/sessions/session-toggle/") {
      await route.fulfill({
        status: 200,
        headers: jsonHeaders,
        body: JSON.stringify([
          { role: "user", content: "seed", created_at: "2026-02-27T00:00:00Z" },
          { role: "assistant", content: "seed answer", created_at: "2026-02-27T00:00:01Z" },
        ]),
      });
      return;
    }

    if ((path === "/chat/message" || path.endsWith("/chat/message/")) && req.method() === "POST") {
      const payload = (req.postDataJSON() ?? {}) as { include_debug?: boolean };
      await route.fulfill({
        status: 200,
        headers: jsonHeaders,
        body: JSON.stringify({
          session_id: "session-toggle",
          trace_id: "trace-toggle",
          mode: "general_info_query",
          language: "en",
          assistant_message: "ok",
          evidence_pack_id: "pack-toggle",
          cards: [
            {
              type: "summary",
              title: "Summary",
              content: "ok",
            },
          ],
          debug: payload.include_debug ? { intent: "general_info_query", trace_id: "trace-toggle" } : {},
          turns: [
            { role: "user", content: "seed", created_at: "2026-02-27T00:00:00Z" },
            { role: "assistant", content: "seed answer", created_at: "2026-02-27T00:00:01Z" },
          ],
        }),
      });
      return;
    }

    await route.fallback();
  });
}

test("chat developer mode toggle does not trigger maximum update depth", async ({ page }) => {
  test.setTimeout(120_000);

  const runtimeErrors: string[] = [];
  page.on("pageerror", (error) => runtimeErrors.push(error.message));
  page.on("console", (msg) => {
    if (msg.type() === "error") runtimeErrors.push(msg.text());
  });

  await mockChatCoreApis(page);
  await page.goto("/chat", { waitUntil: "domcontentloaded" });
  await expect(page.getByRole("heading", { name: "Research Workspace", exact: true })).toBeVisible();
  await page.waitForTimeout(3000);

  const modeSwitch = page.getByRole("switch").first();
  await expect(modeSwitch).toBeVisible();

  for (let i = 0; i < 12; i += 1) {
    await modeSwitch.click();
    await page.waitForTimeout(200);
  }

  await expect(page.getByRole("heading", { name: "Research Workspace", exact: true })).toBeVisible();
  const depthErrors = runtimeErrors.filter((line) => /Maximum update depth exceeded/i.test(line));
  expect(depthErrors).toEqual([]);
});
