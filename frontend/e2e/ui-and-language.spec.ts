import { expect, test, type Page, type Route } from "@playwright/test";

function hasChinese(text: string) {
  return /[\u4e00-\u9fff]/.test(text);
}

async function mockCoreApis(page: Page) {
  const sessionId = "session-e2e-1";
  let turns: Array<{ role: "user" | "assistant" | "system"; content: string; created_at: string }> = [];

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
        headers: { "Content-Type": "text/event-stream; charset=utf-8", "Access-Control-Allow-Origin": "*" },
        body: "data: {\"type\":\"audit.trace\",\"trace_id\":\"t1\",\"session_id\":\"sse\",\"timestamp\":\"2026-02-16T00:00:00Z\",\"payload\":{\"heartbeat\":true}}\n\n",
      });
      return;
    }

    const jsonHeaders = {
      "Access-Control-Allow-Origin": "*",
      "Content-Type": "application/json",
    };

    if (path === "/workbench/tasks") return route.fulfill({ status: 200, headers: jsonHeaders, body: "[]" });
    if (path === "/workbench/datasets") return route.fulfill({ status: 200, headers: jsonHeaders, body: "[]" });
    if (path === "/workbench/runs") return route.fulfill({ status: 200, headers: jsonHeaders, body: "[]" });
    if (path === "/workbench/strategies") return route.fulfill({ status: 200, headers: jsonHeaders, body: "[]" });
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
    if (path === "/trading/approvals") return route.fulfill({ status: 200, headers: jsonHeaders, body: "[]" });

    if (path === "/chat/sessions" || path === "/chat/sessions/") {
      return route.fulfill({
        status: 200,
        headers: jsonHeaders,
        body: JSON.stringify([
          {
            session_id: sessionId,
            last_message: turns.length > 0 ? turns[turns.length - 1].content : "",
            updated_at: "2026-02-16T00:00:00Z",
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
      return route.fulfill({ status: 200, headers: jsonHeaders, body: JSON.stringify(turns) });
    }
    if ((path === "/chat/message" || path.endsWith("/chat/message/")) && req.method() === "POST") {
      const payload = req.postDataJSON() as { message?: string; include_debug?: boolean };
      const message = payload.message ?? "";
      const zh = hasChinese(message);
      const assistant = zh
        ? "这是中文回答：系统已根据中文输入返回中文。"
        : "This is an English reply: output follows input language.";
      turns = [
        {
          role: "user",
          content: message,
          created_at: "2026-02-16T00:00:00Z",
        },
        {
          role: "assistant",
          content: assistant,
          created_at: "2026-02-16T00:00:01Z",
        },
      ];
      return route.fulfill({
        status: 200,
        headers: jsonHeaders,
        body: JSON.stringify({
          session_id: sessionId,
          trace_id: "trace-e2e",
          mode: "general_info_query",
          language: zh ? "zh" : "en",
          assistant_message: assistant,
          evidence_pack_id: "pack-e2e",
          cards: [
            {
              type: "summary",
              title: zh ? "结论" : "Summary",
              content: assistant,
            },
          ],
          debug: payload.include_debug ? { intent: "general_info_query", trace_id: "trace-e2e" } : {},
          turns,
        }),
      });
    }

    return route.fallback();
  });
}

function assertNoMojibake(text: string | null) {
  const body = text ?? "";
  expect(body).not.toContain("锟");
  expect(body).not.toContain("鈻");
}

test("UI labels stay English and render without mojibake", async ({ page }) => {
  await mockCoreApis(page);
  await page.goto("/chat", { waitUntil: "domcontentloaded" });
  await expect(page.getByRole("heading", { name: "Research Workspace", exact: true })).toBeVisible();
  assertNoMojibake(await page.textContent("body"));

  await page.goto("/reports", { waitUntil: "domcontentloaded" });
  await expect(page.getByRole("heading", { name: "Reports", exact: true })).toBeVisible();
  assertNoMojibake(await page.textContent("body"));
});

test("chat output language follows user input language in one session", async ({ page }) => {
  await mockCoreApis(page);
  await page.goto("/chat", { waitUntil: "domcontentloaded" });
  await expect(page.getByRole("heading", { name: "Research Workspace", exact: true })).toBeVisible();

  const zhPayload = await page.evaluate(async () => {
    const resp = await fetch("http://127.0.0.1:8000/chat/message", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: "\u8bf7\u7528\u4e2d\u6587\u5206\u6790\u4e00\u4e0b\u98ce\u9669\u3002" }),
    });
    return resp.json();
  });
  expect(String(zhPayload.language ?? "")).toBe("zh");
  expect(hasChinese(String(zhPayload.assistant_message ?? ""))).toBe(true);
  expect(String(zhPayload.cards?.[0]?.title ?? "")).toBe("结论");

  const enPayload = await page.evaluate(async (sessionId: string) => {
    const resp = await fetch("http://127.0.0.1:8000/chat/message", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: sessionId, message: "Please answer in English now." }),
    });
    return resp.json();
  }, String(zhPayload.session_id));
  expect(String(enPayload.language ?? "")).toBe("en");
  expect(String(enPayload.assistant_message ?? "")).toContain("English reply");
  expect(String(enPayload.cards?.[0]?.title ?? "")).toBe("Summary");

  await expect(page.getByRole("heading", { name: "Research Workspace", exact: true })).toBeVisible();
});
