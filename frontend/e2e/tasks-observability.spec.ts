import { expect, test, type Page, type Route } from "@playwright/test";
import { mkdirSync } from "node:fs";
import * as path from "node:path";

async function mockApis(page: Page) {
  const jsonHeaders = {
    "Access-Control-Allow-Origin": "*",
    "Content-Type": "application/json",
  };
  const parentTaskId = "task-parent-robustness";
  const childTasks = Array.from({ length: 6 }).map((_, i) => ({
    task_id: `task-child-${i + 1}`,
    parent_task_id: parentTaskId,
    task_type: "robustness.variant",
    status: "done",
    progress: 100,
    message: `variant ${i + 1} done`,
    result: {},
    result_ref: {
      run_id: `run-${i + 1}`,
      report_id: `run-${i + 1}`,
      open_path: `/reports/run-${i + 1}`,
    },
    meta: {
      scenario: `cost x${i + 1}`,
      variant_id: `var-${i + 1}`,
    },
    created_at: `2026-02-28T00:0${i}:00Z`,
    updated_at: `2026-02-28T00:1${i}:00Z`,
    error: null,
  }));

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
        body: "data: {\"type\":\"task.progress\",\"trace_id\":\"t1\",\"session_id\":\"workbench\",\"timestamp\":\"2026-02-28T00:00:00Z\",\"payload\":{\"task_id\":\"task-parent-robustness\",\"progress\":88,\"status\":\"running\"}}\n\n",
      });
      return;
    }

    if (path === "/workbench/tasks") {
      const parentTask = {
        task_id: parentTaskId,
        task_type: "robustness.run",
        status: "done",
        progress: 100,
        message: "6/6 variants completed",
        result: { robustness_id: "rob_abc123" },
        result_ref: { open_path: "/reports?tab=robustness&robustness_id=rob_abc123", compare_path: "/reports" },
        meta: { variant_total: 6 },
        created_at: "2026-02-28T00:00:00Z",
        updated_at: "2026-02-28T00:20:00Z",
        error: null,
      };
      await route.fulfill({ status: 200, headers: jsonHeaders, body: JSON.stringify([parentTask, ...childTasks]) });
      return;
    }

    if (path === "/workbench/datasets") return route.fulfill({ status: 200, headers: jsonHeaders, body: "[]" });
    if (path === "/workbench/runs") {
      await route.fulfill({
        status: 200,
        headers: jsonHeaders,
        body: JSON.stringify([
          {
            run_id: "run-1",
            audit_trace_id: "trace-run-1",
            dataset_version: "v1",
            strategy_id: "s1",
            strategy_version: "1.0.0",
            market: "US",
            start: "2025-01-01",
            end: "2025-12-31",
            sharpe: 0.71,
            max_drawdown: 0.12,
          },
        ]),
      });
      return;
    }
    if (path === "/workbench/runs/run-1") {
      await route.fulfill({
        status: 200,
        headers: jsonHeaders,
        body: JSON.stringify({
          run_id: "run-1",
          dataset_version: "v1",
          strategy_version: "1.0.0",
          factor_versions: [],
          audit_trace_id: "trace-run-1",
          created_at: "2026-02-28T00:00:00Z",
          metrics: { sharpe: 0.71, max_drawdown: 0.12, total_return: 0.18 },
          charts: [],
          diagnostics: {},
          evidence_refs: [],
          equity_curve: [],
          orders: [],
          trades: [],
          positions: [],
          cost_breakdown: {},
        }),
      });
      return;
    }
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
      await route.fulfill({ status: 200, headers: jsonHeaders, body: "[]" });
      return;
    }

    await route.fallback();
  });
}

test("tasks page renders parent-child tree with progress and report links", async ({ page }) => {
  await mockApis(page);
  await page.goto("/tasks?focus_task_id=task-parent-robustness", { waitUntil: "domcontentloaded" });

  await expect(page.getByRole("heading", { name: "Tasks", exact: true })).toBeVisible();
  await expect(page.getByText("robustness.run")).toBeVisible();
  await expect(page.getByText("6/6 variants completed").first()).toBeVisible();
  await expect(page.getByRole("link", { name: "Open Compare" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Open Report" })).toHaveCount(6);
  const artifactsDir = path.join(process.cwd(), "e2e", "artifacts");
  mkdirSync(artifactsDir, { recursive: true });
  await page.screenshot({ path: path.join(artifactsDir, "pr-tasks-obs-01-tasks.png"), fullPage: true });

  await page.getByRole("link", { name: "Open Compare" }).first().click();
  await expect(page.getByRole("heading", { name: "Reports", exact: true })).toBeVisible();
  await page.screenshot({ path: path.join(artifactsDir, "pr-tasks-obs-01-reports.png"), fullPage: true });
});
