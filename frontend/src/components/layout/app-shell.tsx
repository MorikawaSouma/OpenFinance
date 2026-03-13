"use client";

import { useEffect, useState } from "react";
import { usePathname } from "next/navigation";

import { Sidebar } from "@/components/layout/sidebar";
import { Topbar } from "@/components/layout/topbar";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { recordRouteChange } from "@/lib/debug";

export function AppShell({ children }: { children: React.ReactNode }) {
  const [mobileOpen, setMobileOpen] = useState(false);
  const pathname = usePathname();

  useEffect(() => {
    recordRouteChange(pathname);
  }, [pathname]);

  return (
    <div className="workspace-shell min-h-screen">
      <div className="flex min-h-screen">
        <div className="hidden xl:block">
          <Sidebar />
        </div>

        <Sheet open={mobileOpen} onOpenChange={setMobileOpen}>
          <SheetContent side="left" className="p-0">
            <SheetHeader className="sr-only">
              <SheetTitle>Navigation</SheetTitle>
              <SheetDescription>OpenFinance workspace navigation</SheetDescription>
            </SheetHeader>
            <Sidebar onNavigate={() => setMobileOpen(false)} />
          </SheetContent>
        </Sheet>

        <div className="min-w-0 flex-1">
          <Topbar onMobileMenu={() => setMobileOpen(true)} />
          <main className="container relative z-10 mx-auto grid max-w-7xl gap-4 px-4 py-6 animate-rise-in">
            {children}
          </main>
        </div>
      </div>
    </div>
  );
}
