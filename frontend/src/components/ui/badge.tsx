import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const badgeVariants = cva(
  "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs font-medium transition-colors",
  {
    variants: {
      variant: {
        default:
          "border-[var(--color-border)] bg-[var(--color-surface-elevated)] text-[var(--color-muted-strong)]",
        success:
          "border-[color:color-mix(in_oklab,var(--color-accent)_40%,transparent)] bg-[color:color-mix(in_oklab,var(--color-accent)_12%,transparent)] text-[var(--color-accent)]",
        warning:
          "border-[color:color-mix(in_oklab,var(--color-warning)_40%,transparent)] bg-[color:color-mix(in_oklab,var(--color-warning)_12%,transparent)] text-[var(--color-warning)]",
        danger:
          "border-[color:color-mix(in_oklab,var(--color-danger)_40%,transparent)] bg-[color:color-mix(in_oklab,var(--color-danger)_12%,transparent)] text-[var(--color-danger)]",
        info:
          "border-[color:color-mix(in_oklab,var(--color-info)_40%,transparent)] bg-[color:color-mix(in_oklab,var(--color-info)_12%,transparent)] text-[var(--color-info)]",
      },
    },
    defaultVariants: { variant: "default" },
  }
);

export interface BadgeProps
  extends React.HTMLAttributes<HTMLSpanElement>,
    VariantProps<typeof badgeVariants> {}

export function Badge({ className, variant, ...props }: BadgeProps) {
  return (
    <span className={cn(badgeVariants({ variant, className }))} {...props} />
  );
}
