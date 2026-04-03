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
        body: "data: {\"type\":\"audit.trace\",\"trace_id\":\"guard-trace\",\"session_id\":\"guard-session\",\"timestamp\":\"2026-03-01T00:00:00Z\",\"payload\":{\"heartbeat\":true}}\n\n",
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
            session_id: "guard-session",
            last_message: "seed",
            updated_at: "2026-03-01T00:00:00Z",
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

    if (path === "/chat/sessions/guard-session" || path === "/chat/sessions/guard-session/") {
      await route.fulfill({
        status: 200,
        headers: jsonHeaders,
        body: JSON.stringify([
          { role: "user", content: "seed", created_at: "2026-03-01T00:00:00Z" },
          { role: "assistant", content: "seed answer", created_at: "2026-03-01T00:00:01Z" },
        ]),
      });
      return;
    }

    if ((path === "/chat/message" || path.endsWith("/chat/message/")) && req.method() === "POST") {
      await route.fulfill({
        status: 200,
        headers: jsonHeaders,
        body: JSON.stringify({
          session_id: "guard-session",
          trace_id: "guard-trace",
          mode: "general_info_query",
          language: "en",
          assistant_message: "ok",
          evidence_pack_id: "pack-guard",
          cards: [
            {
              type: "summary",
              title: "Summary",
              content: "ok",
            },
          ],
          debug: {},
          turns: [
            { role: "user", content: "seed", created_at: "2026-03-01T00:00:00Z" },
            { role: "assistant", content: "seed answer", created_at: "2026-03-01T00:00:01Z" },
          ],
        }),
      });
      return;
    }

    await route.fallback();
  });
}

test("DOM mutation guard mounts at workbench root and tolerates mismatched DOM operations", async ({ page }) => {
  await mockChatCoreApis(page);
  await page.goto("/chat", { waitUntil: "domcontentloaded" });
  await expect(page.getByRole("heading", { name: "Research Workspace", exact: true })).toBeVisible();
  await page.waitForFunction(() => window.__OF_DOM_GUARD_INSTALLED__ === true);

  const guardState = await page.evaluate(() => {
    const parentA = document.createElement("div");
    const parentB = document.createElement("div");
    const child = document.createElement("span");
    const reference = document.createElement("span");
    parentB.appendChild(child);
    parentB.appendChild(reference);

    const removeResult = parentA.removeChild(child);

    const inserted = document.createElement("em");
    const insertResult = parentA.insertBefore(inserted, reference);

    return {
      installed: window.__OF_DOM_GUARD_INSTALLED__ === true,
      removeReturnsChild: removeResult === child,
      childStillOwnedByOriginalParent: child.parentNode === parentB,
      insertReturnsNode: insertResult === inserted,
      insertedAppendedToFallbackParent: inserted.parentNode === parentA,
      insertedAtTail: parentA.lastChild === inserted,
      fallbackParentChildCount: parentA.childNodes.length,
    };
  });

  expect(guardState).toEqual({
    installed: true,
    removeReturnsChild: true,
    childStillOwnedByOriginalParent: true,
    insertReturnsNode: true,
    insertedAppendedToFallbackParent: true,
    insertedAtTail: true,
    fallbackParentChildCount: 1,
  });

  await expect(page.getByRole("heading", { name: "Research Workspace", exact: true })).toBeVisible();
});
