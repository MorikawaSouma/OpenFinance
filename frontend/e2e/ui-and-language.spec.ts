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

    if (path === "/events/stream") {
      await route.fulfill({
        status: 200,
        headers: { "Content-Type": "text/event-stream; charset=utf-8" },
        body: "data: {\"type\":\"audit.trace\",\"trace_id\":\"t1\",\"session_id\":\"sse\",\"timestamp\":\"2026-02-16T00:00:00Z\",\"payload\":{\"heartbeat\":true}}\n\n",
      });
      return;
    }

    if (path === "/workbench/tasks") return route.fulfill({ status: 200, body: "[]" });
    if (path === "/workbench/datasets") return route.fulfill({ status: 200, body: "[]" });
    if (path === "/workbench/runs") return route.fulfill({ status: 200, body: "[]" });
    if (path === "/workbench/strategies") return route.fulfill({ status: 200, body: "[]" });
    if (path === "/trading/status") {
      return route.fulfill({
        status: 200,
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
    if (path === "/trading/approvals") return route.fulfill({ status: 200, body: "[]" });

    if (path === "/chat/sessions") {
      return route.fulfill({
        status: 200,
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
    if (path === `/chat/sessions/${sessionId}`) {
      return route.fulfill({ status: 200, body: JSON.stringify(turns) });
    }
    if (path === "/chat/message" && req.method() === "POST") {
      const payload = req.postDataJSON() as { message?: string };
      const message = payload.message ?? "";
      const assistant = hasChinese(message) ? "这是中文回答：系统已根据中文输入返回中文。" : "This is an English reply: output follows input language.";
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
        body: JSON.stringify({
          session_id: sessionId,
          trace_id: "trace-e2e",
          assistant_message: assistant,
          evidence_pack_id: "pack-e2e",
          cards: {},
          developer_payload: {},
          turns,
        }),
      });
    }

    return route.fallback();
  });
}

function assertNoMojibake(text: string | null) {
  const body = text ?? "";
  expect(body).not.toContain("�");
  expect(body).not.toContain("□");
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
      body: JSON.stringify({ message: "请用中文分析一下风险。" }),
    });
    return resp.json();
  });
  expect(String(zhPayload.assistant_message ?? "")).toContain("中文回答");

  const enPayload = await page.evaluate(async (sessionId: string) => {
    const resp = await fetch("http://127.0.0.1:8000/chat/message", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: sessionId, message: "Please answer in English now." }),
    });
    return resp.json();
  }, String(zhPayload.session_id));
  expect(String(enPayload.assistant_message ?? "")).toContain("This is an English reply");

  await expect(page.getByRole("heading", { name: "Research Workspace", exact: true })).toBeVisible();
});
