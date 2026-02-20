"use client";

import * as React from "react";
import * as ToastPrimitives from "@radix-ui/react-toast";
import { X } from "lucide-react";
import { cva } from "class-variance-authority";

import { cn } from "@/lib/utils";

export type ToastItem = {
  id: string;
  title: string;
  description?: string;
  variant?: "default" | "error" | "success";
};

const toastVariants = cva(
  "group pointer-events-auto relative flex w-full items-start justify-between space-x-3 overflow-hidden rounded-md border p-4 shadow-soft transition-all",
  {
    variants: {
      variant: {
        default: "bg-card text-card-foreground",
        error: "border-destructive/40 bg-destructive/5 text-destructive",
        success: "border-success/40 bg-success/5 text-success",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  }
);

export function ToastViewport({
  items,
  onDismiss,
}: {
  items: ToastItem[];
  onDismiss: (id: string) => void;
}) {
  return (
    <ToastPrimitives.Provider swipeDirection="right">
      {items.map((item) => (
        <ToastPrimitives.Root
          key={item.id}
          open
          onOpenChange={(open) => {
            if (!open) onDismiss(item.id);
          }}
          className={cn(toastVariants({ variant: item.variant }))}
        >
          <div className="grid gap-1">
            <ToastPrimitives.Title className="text-sm font-semibold">{item.title}</ToastPrimitives.Title>
            {item.description ? (
              <ToastPrimitives.Description className="text-xs text-muted-foreground">
                {item.description}
              </ToastPrimitives.Description>
            ) : null}
          </div>
          <ToastPrimitives.Close
            onClick={() => onDismiss(item.id)}
            className="rounded-md p-1 text-muted-foreground hover:bg-muted/40 hover:text-foreground"
          >
            <X className="h-4 w-4" />
          </ToastPrimitives.Close>
        </ToastPrimitives.Root>
      ))}
      <ToastPrimitives.Viewport className="fixed right-4 top-4 z-[100] flex max-h-screen w-[360px] flex-col gap-2 outline-none" />
    </ToastPrimitives.Provider>
  );
}
