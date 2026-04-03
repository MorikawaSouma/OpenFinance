"use client";

import { Activity, Menu, Moon, Sun } from "lucide-react";
import { useTheme } from "next-themes";
import { useEffect, useState } from "react";

import { useCatalogSummaryState } from "@/components/providers/catalog-summary-provider";
import { useRiskApprovalState } from "@/components/providers/risk-approval-provider";
import { useTaskRealtimeState } from "@/components/providers/task-realtime-provider";
import { useWorkbenchShellActions, useWorkbenchShellState } from "@/components/providers/workbench-shell-provider";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { messages } from "@/lib/messages";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

export function Topbar({ onMobileMenu }: { onMobileMenu: () => void }) {
  const { mode } = useWorkbenchShellState();
  const { setMode } = useWorkbenchShellActions();
  const { datasets, runs } = useCatalogSummaryState();
  const { riskSnapshot } = useRiskApprovalState();
  const { activeTasksCount } = useTaskRealtimeState();
  const { resolvedTheme, setTheme } = useTheme();
  const [mounted, setMounted] = useState(false);
  const latestDatasetVersion = datasets[0]?.dataset_version ?? null;
  const latestStrategyVersion = runs[0]?.strategy_version ?? null;

  useEffect(() => {
    setMounted(true);
  }, []);

  return (
    <header className="sticky top-0 z-30 border-b border-border/80 bg-background/86 backdrop-blur-xl">
      <div className="container mx-auto flex h-16 max-w-7xl items-center justify-between px-4">
        <div className="flex min-w-0 items-center gap-2">
          <Button variant="outline" size="icon" className="xl:hidden" onClick={onMobileMenu}>
            <Menu className="h-4 w-4" />
          </Button>
          <Badge variant="muted" className="hidden md:inline-flex">
            {messages.topbar.dataset}: {latestDatasetVersion ?? "-"}
          </Badge>
          <Badge variant="muted" className="hidden md:inline-flex">
            {messages.topbar.strategy}: {latestStrategyVersion ?? "-"}
          </Badge>
          <Badge variant={riskSnapshot?.live_trading_enabled ? "destructive" : "success"} className="hidden sm:inline-flex">
            {messages.topbar.riskGate}: {riskSnapshot?.live_trading_enabled ? messages.topbar.liveEnabled : messages.topbar.liveLocked}
          </Badge>
          <Badge variant={activeTasksCount > 0 ? "warning" : "muted"}>
            <Activity className="mr-1 h-3 w-3" />
            {messages.topbar.runningTasks}: {activeTasksCount}
          </Badge>
        </div>

        <div className="surface-panel-soft flex items-center gap-2 px-2 py-1.5">
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="outline" size="sm">
                {mode === "developer" ? messages.topbar.developerMode : messages.topbar.userMode}
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem onClick={() => setMode("user")}>{messages.topbar.userMode}</DropdownMenuItem>
              <DropdownMenuItem onClick={() => setMode("developer")}>{messages.topbar.developerMode}</DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>

          <button
            type="button"
            role="switch"
            aria-checked={mode === "developer"}
            aria-label="Toggle mode"
            onClick={() => setMode(mode === "developer" ? "user" : "developer")}
            className="inline-flex h-6 w-11 items-center rounded-full border-2 border-transparent bg-input transition-colors"
          >
            <span className="sr-only">Toggle mode</span>
            <span className={`inline-flex h-6 w-11 items-center rounded-full transition-colors ${mode === "developer" ? "bg-primary" : "bg-input"}`}>
              <span
                className={`block h-5 w-5 rounded-full bg-background shadow-lg transition-transform ${
                  mode === "developer" ? "translate-x-5" : "translate-x-0"
                }`}
              />
            </span>
          </button>

          <Button
            variant="outline"
            size="icon"
            onClick={() => setTheme(resolvedTheme === "dark" ? "light" : "dark")}
            aria-label={messages.topbar.toggleTheme}
          >
            {!mounted ? <Moon className="h-4 w-4" /> : resolvedTheme === "dark" ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
          </Button>
        </div>
      </div>
    </header>
  );
}
