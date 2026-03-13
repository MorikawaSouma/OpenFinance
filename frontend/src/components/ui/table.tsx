import type React from "react";

import { cn } from "@/lib/utils";

export function Table(props: React.TableHTMLAttributes<HTMLTableElement>) {
  return (
    <div className="w-full overflow-x-auto rounded-xl border border-border/80 bg-card/72 shadow-[0_8px_24px_rgba(15,23,42,0.06)]">
      <table {...props} className={cn("w-full text-sm", props.className)} />
    </div>
  );
}

export function THead(props: React.HTMLAttributes<HTMLTableSectionElement>) {
  return <thead {...props} className={cn("text-left text-[11px] uppercase tracking-[0.11em] text-muted-foreground", props.className)} />;
}

export function TBody(props: React.HTMLAttributes<HTMLTableSectionElement>) {
  return <tbody {...props} className={cn("divide-y divide-border/70", props.className)} />;
}

export function Tr(props: React.HTMLAttributes<HTMLTableRowElement>) {
  return <tr {...props} className={cn("transition-colors hover:bg-muted/40", props.className)} />;
}

export function Th(props: React.ThHTMLAttributes<HTMLTableCellElement>) {
  return <th {...props} className={cn("px-2 py-2 font-medium", props.className)} />;
}

export function Td(props: React.TdHTMLAttributes<HTMLTableCellElement>) {
  return <td {...props} className={cn("px-2 py-2 align-top", props.className)} />;
}
