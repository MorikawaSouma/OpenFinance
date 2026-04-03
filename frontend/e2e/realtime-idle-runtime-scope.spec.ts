import { expect, test, type Page, type Route } from "@playwright/test";

function riskPayload() {
  return {
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
  };
}

async function installStableSseMock(page: Page) {
  await page.addInitScript(() => {
    const originalFetch = window.fetch.bind(window);
    window.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
      const url =
        typeof input === "string"
          ? input
          : input instanceof URL
            ? input.toString()
            : input instanceof Request
              ? input.url
              : String(input);

      if (!url.includes("/events/stream")) {
        return originalFetch(input, init);
      }

      const encoder = new TextEncoder();
      let timer = 0;
      const stream = new ReadableStream<Uint8Array>({
        start(controller) {
          const write = (chunk: string) => controller.enqueue(encoder.encode(chunk));
          write(": connected\n\n");
          timer = window.setInterval(() => {
            write(": keepalive\n\n");
          }, 5_000);
        },
        cancel() {
          if (timer) {
            window.clearInterval(timer);
          }
        },
      });

      return new Response(stream, {
        status: 200,
        headers: {
          "Access-Control-Allow-Origin": "*",
          "Content-Type": "text/event-stream; charset=utf-8",
        },
      });
    }) as typeof window.fetch;
  });
}

test("idle settings route no longer performs legacy broad 30-second polling", async ({ page }) => {
  test.setTimeout(70_000);

  const jsonHeaders = {
    "Access-Control-Allow-Origin": "*",
    "Content-Type": "application/json",
  };
  const counts = {
    datasets: 0,
    runs: 0,
    strategies: 0,
    riskStatus: 0,
    approvals: 0,
    tasks: 0,
  };

  await installStableSseMock(page);

  await page.route("**/*", async (route: Route) => {
    const req = route.request();
    const path = new URL(req.url()).pathname;

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

    if (path === "/workbench/datasets") {
      counts.datasets += 1;
      await route.fulfill({ status: 200, headers: jsonHeaders, body: "[]" });
      return;
    }

    if (path === "/workbench/runs") {
      counts.runs += 1;
      await route.fulfill({ status: 200, headers: jsonHeaders, body: "[]" });
      return;
    }

    if (path === "/workbench/strategies") {
      counts.strategies += 1;
      await route.fulfill({ status: 200, headers: jsonHeaders, body: "[]" });
      return;
    }

    if (path === "/trading/status") {
      counts.riskStatus += 1;
      await route.fulfill({ status: 200, headers: jsonHeaders, body: JSON.stringify(riskPayload()) });
      return;
    }

    if (path === "/trading/approvals") {
      counts.approvals += 1;
      await route.fulfill({ status: 200, headers: jsonHeaders, body: "[]" });
      return;
    }

    if (path === "/workbench/tasks") {
      counts.tasks += 1;
      await route.fulfill({ status: 200, headers: jsonHeaders, body: "[]" });
      return;
    }

    await route.fallback();
  });

  await page.goto("/settings", { waitUntil: "domcontentloaded" });
  await expect(page.getByRole("heading", { name: "Workspace Settings" })).toBeVisible();

  await page.waitForTimeout(2_500);
  const baseline = { ...counts };

  await page.waitForTimeout(31_500);

  expect(counts).toEqual(baseline);
});
