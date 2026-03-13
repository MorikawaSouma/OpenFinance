import { expect, test, type Page, type Route } from "@playwright/test";
import { mkdirSync } from "node:fs";
import * as path from "node:path";

async function mockApis(page: Page) {
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
        headers: { "Access-Control-Allow-Origin": "*", "Content-Type": "text/event-stream; charset=utf-8" },
        body: "data: {\"type\":\"audit.trace\",\"trace_id\":\"chat-dedup\",\"session_id\":\"s1\",\"timestamp\":\"2026-02-28T00:00:00Z\",\"payload\":{\"heartbeat\":true}}\n\n",
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
            session_id: "session-dedup",
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

    if (path === "/chat/sessions/session-dedup" || path === "/chat/sessions/session-dedup/") {
      await route.fulfill({
        status: 200,
        headers: jsonHeaders,
        body: JSON.stringify([]),
      });
      return;
    }

    if ((path === "/chat/message" || path.endsWith("/chat/message/")) && req.method() === "POST") {
      await route.fulfill({
        status: 200,
        headers: jsonHeaders,
        body: JSON.stringify({
          session_id: "session-dedup",
          trace_id: "trace-dedup",
          message_id: "assistant:2026-02-28T00:00:01Z",
          mode: "market_compare",
          language: "en",
          assistant_message: "US vs JP comparison completed.",
          evidence_pack_id: "pack-us|pack-jp",
          cards: [
            {
              card_id: "assistant:2026-02-28T00:00:01Z:summary:0",
              type: "summary",
              title: "Comparison Summary",
              content: "US is more sensitive while JP is relatively stable.",
            },
            {
              card_id: "assistant:2026-02-28T00:00:01Z:summary:0",
              type: "summary",
              title: "Comparison Summary",
              content: "US is more sensitive while JP is relatively stable.",
            },
            {
              card_id: "assistant:2026-02-28T00:00:01Z:comparison_table:1",
              type: "comparison_table",
              title: "Comparison Table",
              table: [
                { metric: "Drawdown", us: "18.0%", jp: "12.0%", difference: "US is more sensitive." },
                { metric: "Volatility", us: "24.0%", jp: "16.0%", difference: "US is more sensitive." },
              ],
            },
          ],
          debug: { intent: "market_compare" },
          turns: [
            { role: "user", content: "Compare US vs JP", created_at: "2026-02-28T00:00:00Z" },
            { role: "assistant", content: "US vs JP comparison completed.", created_at: "2026-02-28T00:00:01Z" },
          ],
        }),
      });
      return;
    }

    await route.fallback();
  });
}

test("chat cards are deduplicated and stable across route switches", async ({ page }) => {
  await mockApis(page);
  await page.goto("/chat", { waitUntil: "domcontentloaded" });
  await expect(page.getByRole("heading", { name: "Research Workspace", exact: true })).toBeVisible();

  const input = page.getByPlaceholder("Ask anything about markets, factors, strategy, and risk.");
  const send = page.getByRole("button", { name: "Send", exact: true });
  let sent = false;
  for (let i = 0; i < 3; i += 1) {
    await input.fill("Compare US vs JP");
    await expect(input).toHaveValue("Compare US vs JP");
    await send.click();
    try {
      await expect(page.getByText("Comparison Summary")).toBeVisible({ timeout: 3500 });
      sent = true;
      break;
    } catch {
      await page.waitForTimeout(300);
    }
  }
  expect(sent).toBe(true);

  await expect(page.getByText("Comparison Summary")).toHaveCount(1);
  await expect(page.getByText("Comparison Table")).toHaveCount(1);
  await expect(page.getByText("Drawdown")).toBeVisible();
  const artifactsDir = path.join(process.cwd(), "e2e", "artifacts");
  mkdirSync(artifactsDir, { recursive: true });
  await page.screenshot({ path: path.join(artifactsDir, "pr-chat-ui-02-chat.png"), fullPage: true });

  await page.goto("/pipeline", { waitUntil: "domcontentloaded" });
  await page.goto("/chat", { waitUntil: "domcontentloaded" });
  await expect(page.getByText("Comparison Summary")).toHaveCount(1);
  await expect(page.getByText("Comparison Table")).toHaveCount(1);
});
