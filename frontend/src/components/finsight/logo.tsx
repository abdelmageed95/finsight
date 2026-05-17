import Link from "next/link";
import { cn } from "@/lib/utils";

export function Logo({
  className,
  size = "md",
}: {
  className?: string;
  size?: "sm" | "md" | "lg";
}) {
  const sizes = {
    sm: "text-sm",
    md: "text-base",
    lg: "text-lg",
  };
  return (
    <Link
      href="/"
      className={cn(
        "inline-flex items-center gap-2 font-semibold tracking-tight text-[var(--color-foreground)] hover:opacity-90 transition-opacity",
        sizes[size],
        className
      )}
    >
      <span className="relative inline-flex">
        <span className="h-2 w-2 rounded-full bg-[var(--color-accent)]" />
        <span className="absolute inset-0 h-2 w-2 rounded-full bg-[var(--color-accent)] animate-ping opacity-60" />
      </span>
      FinSight
    </Link>
  );
}
