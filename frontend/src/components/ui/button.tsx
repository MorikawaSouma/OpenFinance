"use client";

import * as React from "react";
import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";

import { cn } from "@/lib/utils";

const buttonVariants = cva(
  "inline-flex items-center justify-center whitespace-nowrap rounded-md text-sm font-medium transition-all duration-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background disabled:pointer-events-none disabled:opacity-50",
  {
    variants: {
      variant: {
        default:
          "bg-primary text-primary-foreground shadow-sm hover:-translate-y-[1px] hover:bg-primary/90 hover:shadow-md",
        secondary:
          "bg-secondary text-secondary-foreground shadow-sm hover:-translate-y-[1px] hover:bg-secondary/90",
        destructive:
          "bg-destructive text-destructive-foreground shadow-sm hover:-translate-y-[1px] hover:brightness-105",
        outline:
          "border border-input bg-background/92 text-foreground shadow-[0_1px_0_hsl(var(--card))_inset] hover:-translate-y-[1px] hover:bg-accent hover:text-accent-foreground",
        ghost: "hover:bg-accent/70 hover:text-accent-foreground",
      },
      size: {
        default: "h-9 px-4 py-2 tracking-[0.01em]",
        sm: "h-8 rounded-md px-3 text-xs tracking-[0.01em]",
        lg: "h-10 rounded-md px-6 tracking-[0.01em]",
        icon: "h-9 w-9 rounded-lg",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  }
);

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  asChild?: boolean;
}

const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, asChild = false, ...props }, ref) => {
    const Comp = asChild ? Slot : "button";
    return <Comp className={cn(buttonVariants({ variant, size, className }))} ref={ref} {...props} />;
  }
);
Button.displayName = "Button";

export { Button, buttonVariants };
