import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import { ArrowDownRight, ArrowUpRight } from "lucide-react";

interface KpiCardProps {
  label: string;
  value: string;
  delta?: number | null;
  deltaLabel?: string;
  hint?: string;
  className?: string;
}

export function KpiCard({
  label,
  value,
  delta,
  deltaLabel,
  hint,
  className,
}: KpiCardProps) {
  const hasDelta = delta != null && !Number.isNaN(delta);
  const positive = hasDelta && delta! >= 0;
  return (
    <Card className={cn("hover:border-[var(--color-border-strong)]", className)}>
      <CardHeader>
        <CardTitle>{label}</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="flex items-baseline gap-2">
          <span className="font-mono text-2xl font-semibold tabular-nums text-[var(--color-foreground)]">
            {value}
          </span>
          {hasDelta && (
            <span
              className={cn(
                "inline-flex items-center gap-0.5 text-xs font-medium",
                positive
                  ? "text-[var(--color-accent)]"
                  : "text-[var(--color-danger)]"
              )}
            >
              {positive ? (
                <ArrowUpRight className="h-3 w-3" />
              ) : (
                <ArrowDownRight className="h-3 w-3" />
              )}
              {deltaLabel ?? `${delta!.toFixed(2)}%`}
            </span>
          )}
        </div>
        {hint && (
          <p className="mt-1 text-xs text-[var(--color-muted)]">{hint}</p>
        )}
      </CardContent>
    </Card>
  );
}
