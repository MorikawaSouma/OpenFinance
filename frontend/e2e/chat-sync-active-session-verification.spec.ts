import { expect, test, type Page, type Route } from "@playwright/test";

type SessionId = "session-a" | "session-b" | "session-c";

type Turn = {
  role: "user" | "assistant" | "system";
  content: string;
  created_at: string;
};

const JSON_HEADERS = {
  "Access-Control-Allow-Origin": "*",
  "Content-Type": "application/json",
};

function researchContextRecord(payload: {
  lastSessionId?: string | null;
  lastTraceId?: string | null;
  restoredSessionId?: string | null;
  restoredTraceId?: string | null;
  lastRestoredAt?: string | null;
}) {
  return {
    state: {
      lastSessionId: payload.lastSessionId ?? null,
      lastTraceId: payload.lastTraceId ?? null,
      lastPlanId: null,
      restoredSessionId: payload.restoredSessionId ?? null,
      restoredTraceId: payload.restoredTraceId ?? null,
      lastRestoredAt: payload.lastRestoredAt ?? null,
    },
    version: 1,
  };
}

async function installVerificationInitScript(
  page: Page,
  options: {
    developerMode?: boolean;
    researchContext?: ReturnType<typeof researchContextRecord>;
  } = {}
) {
  await page.addInitScript((payload) => {
    localStorage.clear();
    if (payload.developerMode) {
      localStorage.setItem("of_mode", "developer");
    }
    if (payload.researchContext) {
      localStorage.setItem("research_context_v1", JSON.stringify(payload.researchContext));
    }
  }, options);
}

function seedTurns(sessionId: SessionId): Turn[] {
  return [
    {
      role: "user",
      content: `${sessionId} seeded question`,
      created_at: "2026-03-23T00:00:00.000Z",
    },
    {
      role: "assistant",
      content: `${sessionId} seeded answer`,
      created_at: "2026-03-23T00:00:01.000Z",
    },
  ];
}

async function mockChatApisForSyncVerification(page: Page) {
  const turnsBySession = new Map<SessionId, Turn[]>([
    ["session-a", seedTurns("session-a")],
    ["session-b", seedTurns("session-b")],
    ["session-c", seedTurns("session-c")],
  ]);

  const sentPayloads: Array<{ session_id: string | null; message: string }> = [];

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
        body: 'data: {"event_id":"audit-seed","type":"audit.trace","trace_id":"trace-audit","session_id":"sse","timestamp":"2026-03-23T00:00:00Z","payload":{"heartbeat":true}}\n\n',
      });
      return;
    }

    if (path === "/workbench/tasks" || path === "/workbench/datasets" || path === "/workbench/runs" || path === "/workbench/strategies") {
      await route.fulfill({ status: 200, headers: JSON_HEADERS, body: "[]" });
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
      const rows = (["session-b", "session-a", "session-c"] as SessionId[]).map((sessionId, index) => ({
        session_id: sessionId,
        last_message: `${sessionId} latest`,
        updated_at: `2026-03-23T00:00:0${index + 1}Z`,
        last_plan_id: "",
        last_run_id: "",
        last_report_id: "",
        last_dataset_version: "",
        recent_run_ids: [],
      }));
      await route.fulfill({ status: 200, headers: JSON_HEADERS, body: JSON.stringify(rows) });
      return;
    }

    if (path.startsWith("/chat/sessions/")) {
      const sessionId = path.replace("/chat/sessions/", "") as SessionId;
      await route.fulfill({
        status: 200,
        headers: JSON_HEADERS,
        body: JSON.stringify(turnsBySession.get(sessionId) ?? []),
      });
      return;
    }

    if ((path === "/chat/message" || path.endsWith("/chat/message/")) && req.method() === "POST") {
      const payload = req.postDataJSON() as { message?: string; session_id?: SessionId | null };
      const sessionId = payload.session_id && turnsBySession.has(payload.session_id) ? payload.session_id : "session-a";
      const message = String(payload.message ?? "").trim();
      sentPayloads.push({
        session_id: payload.session_id ? String(payload.session_id) : null,
        message,
      });
      const nextTurns = [
        ...(turnsBySession.get(sessionId) ?? []),
        {
          role: "user",
          content: message,
          created_at: "2026-03-23T00:01:00.000Z",
        },
        {
          role: "assistant",
          content: `reply for ${sessionId}`,
          created_at: "2026-03-23T00:01:01.000Z",
        },
      ] satisfies Turn[];
      turnsBySession.set(sessionId, nextTurns);
      await route.fulfill({
        status: 200,
        headers: JSON_HEADERS,
        body: JSON.stringify({
          session_id: sessionId,
          trace_id: `trace-${sessionId}`,
          mode: "general_info_query",
          language: "en",
          assistant_message: `reply for ${sessionId}`,
          evidence_pack_id: `pack-${sessionId}`,
          cards: [{ type: "summary", title: "Summary", content: `reply for ${sessionId}` }],
          debug: {},
          turns: nextTurns,
        }),
      });
      return;
    }

    await route.fallback();
  });

  return { sentPayloads };
}

async function mockReconnectApisForSyncVerification(page: Page) {
  const turnsBySession = new Map<SessionId, Turn[]>([["session-b", seedTurns("session-b")]]);
  let eventStreamCount = 0;
  let sessionsFetchCount = 0;
  let turnsFetchCount = 0;
  let reconnectTurnInjected = false;

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
      eventStreamCount += 1;
      if (eventStreamCount === 2 && !reconnectTurnInjected) {
        reconnectTurnInjected = true;
        turnsBySession.set("session-b", [
          ...(turnsBySession.get("session-b") ?? []),
          {
            role: "assistant",
            content: "reconnected assistant turn",
            created_at: "2026-03-23T00:02:00.000Z",
          },
        ]);
      }
      const body =
        eventStreamCount === 1
          ? 'id: verify-open-1\ndata: {"event_id":"verify-open-1","type":"audit.trace","trace_id":"trace-open","session_id":"sse","timestamp":"2026-03-23T00:00:00Z","payload":{"heartbeat":true}}\n\n'
          : `id: verify-chat-done-${eventStreamCount}\ndata: {"event_id":"verify-chat-done-${eventStreamCount}","type":"chat.done","trace_id":"trace-reconnect","session_id":"session-b","timestamp":"2026-03-23T00:02:01Z","payload":{"reason":"reconnect-verify"}}\n\n`;
      await route.fulfill({
        status: 200,
        headers: {
          "Access-Control-Allow-Origin": "*",
          "Content-Type": "text/event-stream; charset=utf-8",
        },
        body,
      });
      return;
    }

    if (path === "/workbench/tasks" || path === "/workbench/datasets" || path === "/workbench/runs" || path === "/workbench/strategies") {
      await route.fulfill({ status: 200, headers: JSON_HEADERS, body: "[]" });
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
      sessionsFetchCount += 1;
      await route.fulfill({
        status: 200,
        headers: JSON_HEADERS,
        body: JSON.stringify([
          {
            session_id: "session-b",
            last_message: reconnectTurnInjected ? "session-b reconnected latest" : "session-b latest",
            updated_at: "2026-03-23T00:00:01Z",
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

    if (path === "/chat/sessions/session-b" || path === "/chat/sessions/session-b/") {
      turnsFetchCount += 1;
      await route.fulfill({
        status: 200,
        headers: JSON_HEADERS,
        body: JSON.stringify(turnsBySession.get("session-b") ?? []),
      });
      return;
    }

    if ((path === "/chat/message" || path.endsWith("/chat/message/")) && req.method() === "POST") {
      await route.fulfill({
        status: 200,
        headers: JSON_HEADERS,
        body: JSON.stringify({
          session_id: "session-b",
          trace_id: "trace-session-b",
          mode: "general_info_query",
          language: "en",
          assistant_message: "reply for session-b",
          evidence_pack_id: "pack-session-b",
          cards: [],
          debug: {},
          turns: turnsBySession.get("session-b") ?? [],
        }),
      });
      return;
    }

    await route.fallback();
  });

  return {
    getEventStreamCount: () => eventStreamCount,
    getSessionsFetchCount: () => sessionsFetchCount,
    getTurnsFetchCount: () => turnsFetchCount,
  };
}

async function readResearchContextLastSessionId(page: Page) {
  return page.evaluate(() => {
    const raw = window.localStorage.getItem("research_context_v1");
    if (!raw) return null;
    const parsed = JSON.parse(raw) as { state?: { lastSessionId?: string | null } };
    return parsed.state?.lastSessionId ?? null;
  });
}

test("chat send, session switch, and restore priority still work with research continuity ownership", async ({ page }) => {
  await installVerificationInitScript(page, {
    researchContext: researchContextRecord({
      lastSessionId: "session-a",
      lastTraceId: "trace-old",
      restoredSessionId: "session-c",
      restoredTraceId: "trace-research",
      lastRestoredAt: "2026-03-23T00:00:00.000Z",
    }),
  });
  const apiStats = await mockChatApisForSyncVerification(page);

  await page.goto("/chat?session_id=session-b&restored_trace_id=trace-route", { waitUntil: "domcontentloaded" });

  await expect(page.getByText("Context restored to trace_id=trace-route. You can continue from here.")).toBeVisible();
  await expect(page.getByText("session-b seeded answer")).toBeVisible();

  await page.getByRole("button", { name: /session-c latest/i }).click();
  await expect(page.getByText("session-c seeded answer")).toBeVisible();

  const input = page.getByPlaceholder("Ask anything about markets, factors, strategy, and risk.");
  await input.fill("send through session c");
  await page.getByRole("button", { name: "Send", exact: true }).click();

  await expect(page.getByText("reply for session-c")).toBeVisible();
  await expect
    .poll(() => apiStats.sentPayloads.at(-1)?.session_id ?? null)
    .toBe("session-c");

  await expect
    .poll(async () => readResearchContextLastSessionId(page))
    .toBe("session-c");
});

test("chat reconnect and event-driven freshness still work with research continuity ownership", async ({ page }) => {
  await installVerificationInitScript(page, {
    developerMode: true,
    researchContext: researchContextRecord({
      lastSessionId: "session-a",
      lastTraceId: "trace-old",
    }),
  });
  const reconnectStats = await mockReconnectApisForSyncVerification(page);

  await page.goto("/chat?session_id=session-b", { waitUntil: "domcontentloaded" });
  await expect(page.getByText("session-b seeded answer")).toBeVisible();

  await expect.poll(() => reconnectStats.getEventStreamCount()).toBeGreaterThanOrEqual(2);
  await expect.poll(() => reconnectStats.getSessionsFetchCount()).toBeGreaterThanOrEqual(2);
  await expect.poll(() => reconnectStats.getTurnsFetchCount()).toBeGreaterThanOrEqual(2);
  await expect(page.getByText("reconnected assistant turn")).toBeVisible();

  await expect.poll(async () => {
    const snapshot = await page.evaluate(() => {
      const debug = (window as typeof window & { __OF_DEBUG__?: { sse?: { openCount?: number; reconnectCount?: number } } }).__OF_DEBUG__;
      return {
        openCount: debug?.sse?.openCount ?? 0,
        reconnectCount: debug?.sse?.reconnectCount ?? 0,
      };
    });
    return snapshot.openCount >= 2 && snapshot.reconnectCount >= 1;
  }).toBe(true);

  await expect
    .poll(async () => readResearchContextLastSessionId(page))
    .toBe("session-b");
});
