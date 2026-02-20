import { Inbox } from "lucide-react";

export function EmptyState({
  title,
  description,
}: {
  title: string;
  description: string;
}) {
  return (
    <div className="surface-panel flex min-h-[170px] flex-col items-center justify-center border-dashed p-6 text-center">
      <div className="mb-2 grid h-9 w-9 place-items-center rounded-full bg-muted/80">
        <Inbox className="h-4 w-4 text-muted-foreground" />
      </div>
      <p className="text-sm font-semibold">{title}</p>
      <p className="mt-1 max-w-[32ch] text-xs text-muted-foreground">{description}</p>
    </div>
  );
}
