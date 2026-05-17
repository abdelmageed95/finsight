"use client";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { formatCurrency } from "@/lib/utils";
import type { FinancialsMetrics } from "@/lib/schemas";

interface FinancialsTrendChartProps {
  data: FinancialsMetrics[];
}

export function FinancialsTrendChart({ data }: FinancialsTrendChartProps) {
  // Filter to periods that have revenue or net_income, sort chronologically
  const periods = data
    .filter((d) => d.revenue != null || d.net_income != null)
    .sort((a, b) => (a.period ?? "").localeCompare(b.period ?? ""));

  if (periods.length < 2) return null;

  // Find max value for scaling
  const maxVal = Math.max(
    ...periods.map((p) => Math.abs(p.revenue ?? 0)),
    ...periods.map((p) => Math.abs(p.net_income ?? 0)),
    1
  );

  return (
    <Card>
      <CardHeader>
        <CardTitle>Financial trends</CardTitle>
      </CardHeader>
      <CardContent>
        {/* Legend */}
        <div className="mb-4 flex items-center gap-4 text-xs text-[var(--color-muted)]">
          <span className="flex items-center gap-1.5">
            <span className="inline-block h-2.5 w-2.5 rounded-sm bg-[var(--color-accent)]" />
            Revenue
          </span>
          <span className="flex items-center gap-1.5">
            <span className="inline-block h-2.5 w-2.5 rounded-sm bg-[#8b5cf6]" />
            Net income
          </span>
        </div>

        <div className="space-y-3">
          {periods.map((p) => {
            const revPct = ((p.revenue ?? 0) / maxVal) * 100;
            const niPct = ((p.net_income ?? 0) / maxVal) * 100;
            const niNeg = (p.net_income ?? 0) < 0;

            return (
              <div key={p.period}>
                <div className="mb-1 flex items-baseline justify-between">
                  <span className="font-mono text-xs font-medium text-[var(--color-foreground)]">
                    {p.period}
                  </span>
                  <div className="flex gap-3 text-[10px] text-[var(--color-muted)]">
                    <span>Rev: {p.revenue != null ? formatCurrency(p.revenue, 0) : "—"}</span>
                    <span>NI: {p.net_income != null ? formatCurrency(p.net_income, 0) : "—"}</span>
                  </div>
                </div>
                <div className="space-y-1">
                  {/* Revenue bar */}
                  <div className="h-3 w-full rounded-sm bg-[var(--color-surface)]">
                    <div
                      className="h-full rounded-sm bg-[var(--color-accent)] transition-all"
                      style={{ width: `${Math.max(revPct, 0.5)}%` }}
                    />
                  </div>
                  {/* Net income bar */}
                  <div className="h-3 w-full rounded-sm bg-[var(--color-surface)]">
                    <div
                      className={`h-full rounded-sm transition-all ${
                        niNeg ? "bg-[var(--color-danger)]" : "bg-[#8b5cf6]"
                      }`}
                      style={{ width: `${Math.max(Math.abs(niPct), 0.5)}%` }}
                    />
                  </div>
                </div>
              </div>
            );
          })}
        </div>

        {/* Gross margin trend if available */}
        {periods.some((p) => p.gross_margin != null) && (
          <div className="mt-6 border-t border-[var(--color-border)] pt-4">
            <p className="mb-2 text-xs text-[var(--color-muted)]">Gross margin trend</p>
            <div className="flex items-end gap-1" style={{ height: 48 }}>
              {periods.map((p) => {
                const gm = p.gross_margin ?? 0;
                const heightPct = Math.max(gm * 100, 2);
                return (
                  <div
                    key={p.period}
                    className="group relative flex-1"
                    style={{ height: "100%" }}
                  >
                    <div
                      className="absolute bottom-0 w-full rounded-t-sm bg-[var(--color-accent)]/60 transition-colors group-hover:bg-[var(--color-accent)]"
                      style={{ height: `${heightPct}%` }}
                    />
                    <div className="absolute -top-5 left-1/2 -translate-x-1/2 whitespace-nowrap rounded bg-[var(--color-surface)] px-1.5 py-0.5 text-[9px] text-[var(--color-muted)] opacity-0 shadow transition-opacity group-hover:opacity-100">
                      {(gm * 100).toFixed(1)}%
                    </div>
                  </div>
                );
              })}
            </div>
            <div className="mt-1 flex gap-1">
              {periods.map((p) => (
                <span
                  key={p.period}
                  className="flex-1 text-center text-[8px] text-[var(--color-muted)]"
                >
                  {(p.period ?? "").replace("-", "\n")}
                </span>
              ))}
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
