"use client";

import { Activity, Menu, Moon, Sun } from "lucide-react";
import { useTheme } from "next-themes";
import { useEffect, useState } from "react";

import { useWorkbench } from "@/components/providers/workbench-provider";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { messages } from "@/lib/messages";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Switch } from "@/components/ui/switch";

export function Topbar({ onMobileMenu }: { onMobileMenu: () => void }) {
  const { mode, setMode, latestDatasetVersion, latestStrategyVersion, risk, activeTasksCount } = useWorkbench();
  const { resolvedTheme, setTheme } = useTheme();
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
  }, []);

  return (
    <header className="sticky top-0 z-30 border-b border-border/80 bg-background/88 backdrop-blur-xl">
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
          <Badge variant={risk?.live_trading_enabled ? "destructive" : "success"} className="hidden sm:inline-flex">
            {messages.topbar.riskGate}: {risk?.live_trading_enabled ? messages.topbar.liveEnabled : messages.topbar.liveLocked}
          </Badge>
          <Badge variant={activeTasksCount > 0 ? "warning" : "muted"}>
            <Activity className="mr-1 h-3 w-3" />
            {messages.topbar.runningTasks}: {activeTasksCount}
          </Badge>
        </div>

        <div className="surface-panel-soft flex items-center gap-2 px-2 py-1">
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

          <Switch checked={mode === "developer"} onCheckedChange={(next) => setMode(next ? "developer" : "user")} />

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
