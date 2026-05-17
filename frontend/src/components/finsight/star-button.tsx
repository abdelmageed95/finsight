"use client";

import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Star } from "lucide-react";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";

/**
 * Toggle the starred state of a report. Optimistic — flips locally first,
 * rolls back on error. Invalidates report+history queries on success.
 */
export function StarButton({
  jobId,
  starred,
  size = "sm",
  className,
}: {
  jobId: string;
  starred: boolean;
  size?: "sm" | "md";
  className?: string;
}) {
  const [optimistic, setOptimistic] = useState<boolean>(starred);
  const [pending, setPending] = useState(false);
  const qc = useQueryClient();

  // Sync if the prop changes (e.g. after an external invalidate)
  if (optimistic !== starred && !pending) {
    // Defer this state update to avoid render-loop warnings
    Promise.resolve().then(() => setOptimistic(starred));
  }

  async function toggle(e: React.MouseEvent) {
    e.preventDefault();
    e.stopPropagation();
    if (pending) return;
    const prev = optimistic;
    setOptimistic(!prev);
    setPending(true);
    try {
      const res = await api.toggleStar(jobId);
      setOptimistic(res.is_starred);
      qc.invalidateQueries({ queryKey: ["history"] });
      qc.invalidateQueries({ queryKey: ["report", jobId] });
    } catch {
      setOptimistic(prev);
    } finally {
      setPending(false);
    }
  }

  const iconSize = size === "md" ? "h-4 w-4" : "h-3.5 w-3.5";
  const padding = size === "md" ? "p-1.5" : "p-1";

  return (
    <button
      type="button"
      onClick={toggle}
      disabled={pending}
      title={optimistic ? "Unstar report" : "Star this report"}
      aria-label={optimistic ? "Unstar report" : "Star report"}
      className={cn(
        "inline-flex items-center justify-center rounded-md border border-transparent transition-colors",
        padding,
        optimistic
          ? "text-[var(--color-warning)] hover:bg-[var(--color-warning)]/10"
          : "text-[var(--color-muted)] hover:border-[var(--color-border)] hover:text-[var(--color-warning)]",
        className,
      )}
    >
      <Star className={cn(iconSize, optimistic && "fill-current")} />
    </button>
  );
}
