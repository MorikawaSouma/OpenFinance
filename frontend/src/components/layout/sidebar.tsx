"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { navItems } from "@/components/layout/nav-items";
import { messages } from "@/lib/messages";
import { cn } from "@/lib/utils";

export function Sidebar({ onNavigate }: { onNavigate?: () => void }) {
  const pathname = usePathname();
  return (
    <aside className="flex h-full w-[270px] flex-col border-r bg-card/70 backdrop-blur-xl">
      <div className="border-b px-4 py-5">
        <div className="metric-chip mb-2 w-fit">
          <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
          Online
        </div>
        <p className="text-[11px] uppercase tracking-[0.18em] text-muted-foreground">{messages.product.name}</p>
        <h1 className="mt-1 text-lg font-semibold tracking-tight">{messages.product.subtitle}</h1>
      </div>
      <div className="px-4 pt-3 text-[10px] uppercase tracking-[0.16em] text-muted-foreground">Workspace</div>
      <nav className="space-y-1 p-3">
        {navItems.map((item) => {
          const Icon = item.icon;
          const active = pathname === item.href || (item.href !== "/" && pathname.startsWith(item.href));
          return (
            <Link
              key={item.href}
              href={item.href}
              onClick={onNavigate}
              className={cn(
                "nav-pill elevate-hover flex items-center gap-2 px-3 py-2 text-sm",
                active
                  ? "bg-primary text-primary-foreground shadow-sm"
                  : "text-muted-foreground hover:bg-accent hover:text-accent-foreground"
              )}
            >
              <span className={cn("grid h-6 w-6 place-items-center rounded-md", active ? "bg-white/20" : "bg-muted/60")}>
                <Icon className="h-3.5 w-3.5" />
              </span>
              <span>{item.label}</span>
            </Link>
          );
        })}
      </nav>
    </aside>
  );
}
