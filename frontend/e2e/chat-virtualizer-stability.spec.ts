import { expect, test, type Page, type Route } from "@playwright/test";

type Turn = {
  role: "user" | "assistant" | "system";
  content: string;
  created_at: string;
};

type SessionId = "session-a" | "session-b" | "session-c";

const SESSION_ORDER: SessionId[] = ["session-a", "session-b", "session-c"];
const SESSION_TITLE: Record<SessionId, string> = {
  "session-a": "Session A",
  "session-b": "Session B",
  "session-c": "Session C",
};

function buildAssistantReply(sessionId: string, n: number) {
  const lines = Array.from({ length: 6 + (n % 7) }, (_, i) => `- ${sessionId} insight ${n}.${i + 1}`);
  return `assistant reply #${n} (${sessionId})\n${lines.join("\n")}`;
}

async function mockChatApis(page: Page) {
  const turnsBySession = new Map<SessionId, Turn[]>();
  const sequenceBySession = new Map<SessionId, number>();
  const stats = {
    chatMessageCalls: 0,
    chatMessagePaths: [] as string[],
  };
  const jsonHeaders = {
    "Access-Control-Allow-Origin": "*",
    "Content-Type": "application/json",
  };

  for (const sessionId of SESSION_ORDER) {
    const turns: Turn[] = [];
    for (let i = 0; i < 14; i += 1) {
      turns.push({
        role: "user",
        content: `${SESSION_TITLE[sessionId]} seed user ${i + 1}`,
        created_at: `2026-02-27T00:${String(i).padStart(2, "0")}:00.000Z`,
      });
      turns.push({
        role: "assistant",
        content: buildAssistantReply(sessionId, i + 1),
        created_at: `2026-02-27T00:${String(i).padStart(2, "0")}:30.000Z`,
      });
    }
    turnsBySession.set(sessionId, turns);
    sequenceBySession.set(sessionId, turns.length / 2);
  }

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
        body: "data: {\"type\":\"audit.trace\",\"trace_id\":\"t-chat\",\"session_id\":\"sse\",\"timestamp\":\"2026-02-27T00:00:00Z\",\"payload\":{\"heartbeat\":true}}\n\n",
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
      const rows = SESSION_ORDER.map((sessionId, idx) => {
        const turns = turnsBySession.get(sessionId) ?? [];
        const lastMessage = turns.length > 0 ? turns[turns.length - 1].content.split("\n")[0] : "empty";
        return {
          session_id: sessionId,
          last_message: `${SESSION_TITLE[sessionId]} | ${lastMessage}`,
          updated_at: `2026-02-27T00:00:${String(10 + idx).padStart(2, "0")}Z`,
          last_plan_id: "",
          last_run_id: "",
          last_report_id: "",
          last_dataset_version: "",
          recent_run_ids: [],
        };
      });
      return route.fulfill({ status: 200, headers: jsonHeaders, body: JSON.stringify(rows) });
    }

    if (path.startsWith("/chat/sessions/")) {
      const sessionId = path.replace("/chat/sessions/", "") as SessionId;
      const turns = turnsBySession.get(sessionId) ?? [];
      return route.fulfill({ status: 200, headers: jsonHeaders, body: JSON.stringify(turns) });
    }

    if ((path === "/chat/message" || path.endsWith("/chat/message/")) && req.method() === "POST") {
      stats.chatMessageCalls += 1;
      stats.chatMessagePaths.push(path);
      const payload = req.postDataJSON() as { message?: string; session_id?: SessionId | null; include_debug?: boolean };
      const sessionId = payload.session_id && turnsBySession.has(payload.session_id) ? payload.session_id : "session-a";
      const message = String(payload.message ?? "").trim();
      const turns = turnsBySession.get(sessionId) ?? [];
      const nextSeq = (sequenceBySession.get(sessionId) ?? 0) + 1;
      sequenceBySession.set(sessionId, nextSeq);
      const userTime = `2026-02-27T01:${String(nextSeq).padStart(2, "0")}:00.000Z`;
      const assistantTime = `2026-02-27T01:${String(nextSeq).padStart(2, "0")}:30.000Z`;
      const assistant = buildAssistantReply(sessionId, nextSeq);
      turns.push(
        { role: "user", content: message, created_at: userTime },
        { role: "assistant", content: assistant, created_at: assistantTime }
      );
      turnsBySession.set(sessionId, turns);
      return route.fulfill({
        status: 200,
        headers: jsonHeaders,
        body: JSON.stringify({
          session_id: sessionId,
          trace_id: `trace-${sessionId}-${nextSeq}`,
          mode: "general_info_query",
          language: "en",
          assistant_message: assistant,
          evidence_pack_id: `pack-${sessionId}`,
          cards: [
            {
              type: "summary",
              title: "Summary",
              content: assistant.split("\n")[0],
            },
            {
              type: "evidence",
              title: "Key Evidence",
              items: [
                {
                  title: `${sessionId} source ${nextSeq}`,
                  source: "mock",
                  ts: "2026-02-27T00:00:00Z",
                  snippet: "mock snippet",
                },
              ],
            },
          ],
          debug: payload.include_debug
            ? { intent: "general_info_query", trace_id: `trace-${sessionId}-${nextSeq}`, evidence_pack_id: `pack-${sessionId}` }
            : {},
          turns,
        }),
      });
    }

    return route.fallback();
  });

  return stats;
}

async function fillChatInputStable(page: Page, value: string) {
  for (let i = 0; i < 8; i += 1) {
    const input = page.getByPlaceholder("Ask anything about markets, factors, strategy, and risk.");
    await input.fill(value);
    try {
      await expect(input).toHaveValue(value, { timeout: 700 });
      return;
    } catch {
      await page.waitForTimeout(120);
    }
  }
  throw new Error("chat input did not stabilize");
}

test("chat virtualizer is stable under send/switch/scroll stress", async ({ page }) => {
  test.setTimeout(120_000);
  const runtimeErrors: string[] = [];
  page.on("pageerror", (error) => runtimeErrors.push(error.message));
  page.on("console", (msg) => {
    if (msg.type() === "error") runtimeErrors.push(msg.text());
  });

  await page.addInitScript(() => {
    localStorage.setItem("of_mode", "developer");
  });
  const apiStats = await mockChatApis(page);
  await page.goto("/chat", { waitUntil: "domcontentloaded" });
  await expect(page.getByRole("heading", { name: "Research Workspace", exact: true })).toBeVisible();
  await page.waitForTimeout(4000);

  const sendButton = page.getByRole("button", { name: "Send", exact: true });

  for (let i = 0; i < 20; i += 1) {
    const text = `stress message ${i + 1}`;
    await fillChatInputStable(page, text);
    await sendButton.click();
    await expect(page.getByPlaceholder("Ask anything about markets, factors, strategy, and risk.")).toHaveValue("", {
      timeout: 10_000,
    });
  }

  const chatScrollContainer = page.locator("div.overflow-y-auto").first();
  await chatScrollContainer.evaluate((el) => {
    el.scrollTop = 0;
    el.dispatchEvent(new Event("scroll"));
  });

  const sessionA = page.getByRole("button", { name: /Session A \|/, exact: false });
  const sessionB = page.getByRole("button", { name: /Session B \|/, exact: false });
  const sessionC = page.getByRole("button", { name: /Session C \|/, exact: false });
  await expect(sessionA).toBeVisible();
  await expect(sessionB).toBeVisible();
  await expect(sessionC).toBeVisible();

  await sessionB.click();
  await sessionC.click();
  await sessionB.click();
  await sessionA.click();
  await sessionC.click();

  await expect(page.getByRole("heading", { name: "Research Workspace", exact: true })).toBeVisible();

  const updateDepthErrors = runtimeErrors.filter((line) => /Maximum update depth exceeded/i.test(line));
  expect(updateDepthErrors).toEqual([]);
  expect(apiStats.chatMessageCalls).toBeGreaterThanOrEqual(1);

  const debugSnapshot = await page.evaluate(() => window.__OF_DEBUG__);
  expect(debugSnapshot).toBeTruthy();
  expect((debugSnapshot?.componentMounts?.ChatPage ?? 0)).toBeLessThanOrEqual(3);
  expect((debugSnapshot?.componentUnmounts?.ChatPage ?? 0)).toBeLessThanOrEqual(3);
});
