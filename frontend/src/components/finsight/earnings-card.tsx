"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

interface EarningsEvent {
  date: string;
  eps_estimate: number | null;
  eps_actual: number | null;
  surprise_pct: number | null;
}

interface EarningsResponse {
  ticker: string;
  events: EarningsEvent[];
}

export function EarningsCard({ ticker }: { ticker: string }) {
  const { data } = useQuery({
    queryKey: ["earnings", ticker],
    queryFn: () => api.earnings(ticker) as Promise<EarningsResponse>,
    retry: false,
    staleTime: 1000 * 60 * 30,
  });

  if (!data || data.events.length === 0) return null;

  // Split into past (has actual) and future (no actual)
  const past = data.events.filter((e) => e.eps_actual != null).slice(0, 8);
  const future = data.events.filter((e) => e.eps_actual == null).slice(0, 2);

  // Max EPS for bar scaling
  const allEps = past.flatMap((e) => [e.eps_estimate, e.eps_actual].filter((v): v is number => v != null));
  const maxEps = allEps.length > 0 ? Math.max(...allEps.map(Math.abs)) : 1;

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle>Earnings</CardTitle>
          {future.length > 0 && (
            <span className="text-[10px] text-[var(--color-muted)]">
              Next: {future[0].date}
            </span>
          )}
        </div>
      </CardHeader>
      <CardContent>
        {/* EPS beat/miss bars */}
        <div className="space-y-1.5">
          {past.map((e, i) => {
            const beat = e.eps_actual != null && e.eps_estimate != null && e.eps_actual >= e.eps_estimate;
            const barColor = beat ? "var(--color-accent)" : "var(--color-danger)";
            const barWidth = e.eps_actual != null ? Math.min((Math.abs(e.eps_actual) / maxEps) * 100, 100) : 0;

            return (
              <div key={i} className="flex items-center gap-2">
                <span className="w-[68px] shrink-0 text-[10px] text-[var(--color-muted)]">
                  {e.date}
                </span>
                <div className="flex-1 flex items-center gap-1.5">
                  <div className="flex-1 h-3 rounded-sm bg-[var(--color-surface)] overflow-hidden">
                    <div
                      className="h-full rounded-sm transition-all"
                      style={{ width: `${barWidth}%`, backgroundColor: barColor }}
                    />
                  </div>
                  <span className="w-10 text-right text-[10px] tabular-nums text-[var(--color-foreground)]">
                    {e.eps_actual?.toFixed(2) ?? "—"}
                  </span>
                </div>
                {e.surprise_pct != null && (
                  <span
                    className="w-12 text-right text-[10px] tabular-nums font-medium"
                    style={{ color: e.surprise_pct >= 0 ? "var(--color-accent)" : "var(--color-danger)" }}
                  >
                    {e.surprise_pct >= 0 ? "+" : ""}{e.surprise_pct.toFixed(1)}%
                  </span>
                )}
              </div>
            );
          })}
        </div>

        {/* Legend */}
        <div className="mt-3 flex items-center gap-3 text-[10px] text-[var(--color-muted)]">
          <div className="flex items-center gap-1">
            <span className="inline-block h-2 w-2 rounded-sm" style={{ backgroundColor: "var(--color-accent)" }} />
            Beat
          </div>
          <div className="flex items-center gap-1">
            <span className="inline-block h-2 w-2 rounded-sm" style={{ backgroundColor: "var(--color-danger)" }} />
            Miss
          </div>
          <span className="ml-auto">Est | Actual | Surprise</span>
        </div>
      </CardContent>
    </Card>
  );
}
