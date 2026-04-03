import { expect, test, type Page, type Route } from "@playwright/test";

const JSON_HEADERS = {
  "Access-Control-Allow-Origin": "*",
  "Content-Type": "application/json",
};

async function mockRiskRealtimeApis(page: Page) {
  let riskStatusCalls = 0;
  let approvalsCalls = 0;

  const staleRiskStatus = {
    mode: "paper",
    kill_switch_enabled: false,
    live_trading_enabled: false,
    paper_trading_enabled: false,
    risk_max_order_qty: 1000,
    live_approval_state: "locked",
    paper_approval_state: "requested",
    pending_approval_count: 0,
    current_drawdown: 0.01,
    current_volatility: 0.12,
    max_account_drawdown_limit: 0.05,
    abnormal_volatility_limit: 0.25,
    recent_risk_events: [],
  };

  const refreshedRiskStatus = {
    ...staleRiskStatus,
    live_approval_state: "pending",
    pending_approval_count: 2,
    recent_risk_events: [
      {
        event_id: "risk-evt-1",
        event_type: "drawdown_warn",
        severity: "high",
        message: "VaR breached",
        source: "risk-engine",
        metrics: {},
        created_at: "2026-03-23T00:00:10Z",
      },
    ],
  };

  const refreshedApprovals = [
    {
      request_id: "apr-1",
      target: "live_trading",
      action: "request_trade_enable",
      status: "pending",
      context: {},
      created_at: "2026-03-23T00:00:09Z",
      updated_at: "2026-03-23T00:00:10Z",
      expires_at: null,
      transitions: [],
    },
    {
      request_id: "apr-2",
      target: "paper_trading",
      action: "request_trade_enable",
      status: "pending",
      context: {},
      created_at: "2026-03-23T00:00:09Z",
      updated_at: "2026-03-23T00:00:10Z",
      expires_at: null,
      transitions: [],
    },
  ];

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
        body: [
          'id: risk-evt-1',
          'data: {"event_id":"risk-evt-1","type":"risk.event","trace_id":"trace-risk","session_id":"global","timestamp":"2026-03-23T00:00:10Z","payload":{"event_type":"drawdown_warn","message":"VaR breached"}}',
          "",
          'id: approval-evt-1',
          'data: {"event_id":"approval-evt-1","type":"approval.status_changed","trace_id":"trace-approval","session_id":"global","timestamp":"2026-03-23T00:00:11Z","payload":{"request_id":"apr-1","status":"pending"}}',
          "",
        ].join("\n"),
      });
      return;
    }

    if (path === "/workbench/tasks" || path === "/workbench/datasets" || path === "/workbench/runs" || path === "/workbench/strategies") {
      await route.fulfill({ status: 200, headers: JSON_HEADERS, body: "[]" });
      return;
    }

    if (path === "/chat/sessions" || path === "/chat/sessions/") {
      await route.fulfill({ status: 200, headers: JSON_HEADERS, body: "[]" });
      return;
    }

    if (path === "/trading/status") {
      riskStatusCalls += 1;
      const payload = riskStatusCalls === 1 ? staleRiskStatus : refreshedRiskStatus;
      await route.fulfill({ status: 200, headers: JSON_HEADERS, body: JSON.stringify(payload) });
      return;
    }

    if (path === "/trading/approvals") {
      approvalsCalls += 1;
      const payload = approvalsCalls === 1 ? [] : refreshedApprovals;
      await route.fulfill({ status: 200, headers: JSON_HEADERS, body: JSON.stringify(payload) });
      return;
    }

    if (path.startsWith("/trading/risk/events")) {
      await route.fulfill({
        status: 200,
        headers: JSON_HEADERS,
        body: JSON.stringify(refreshedRiskStatus.recent_risk_events),
      });
      return;
    }

    if (path.startsWith("/trading/live/logs")) {
      await route.fulfill({ status: 200, headers: JSON_HEADERS, body: "[]" });
      return;
    }

    await route.fallback();
  });

  return {
    getRiskStatusCalls: () => riskStatusCalls,
    getApprovalsCalls: () => approvalsCalls,
  };
}

test("risk/settings pages reflect realtime risk and approval freshness", async ({ page }) => {
  const stats = await mockRiskRealtimeApis(page);

  await page.goto("/settings", { waitUntil: "domcontentloaded" });
  await expect.poll(() => stats.getRiskStatusCalls()).toBeGreaterThan(1);
  await expect.poll(() => stats.getApprovalsCalls()).toBeGreaterThan(1);
  await expect(page.getByText("pending: 2")).toBeVisible();
  await expect(page.getByText("live state: pending")).toBeVisible();
  await expect(page.getByRole("cell", { name: "apr-1" })).toBeVisible();

  await page.goto("/risk", { waitUntil: "domcontentloaded" });
  await expect(page.getByText("pending: 2")).toBeVisible();
  await expect(page.getByText("live state: pending")).toBeVisible();
  await expect(page.getByRole("cell", { name: "VaR breached" })).toBeVisible();
});
