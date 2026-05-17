"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

interface DividendResponse {
  ticker: string;
  dividend_yield: number | null;
  payout_ratio: number | null;
  history: { year: number; amount: number }[];
}

export function DividendCard({ ticker }: { ticker: string }) {
  const { data } = useQuery({
    queryKey: ["dividends", ticker],
    queryFn: () => api.dividends(ticker) as Promise<DividendResponse>,
    retry: false,
    staleTime: 1000 * 60 * 30,
  });

  if (!data) return null;

  const hasYield = data.dividend_yield != null;
  const hasHistory = data.history.length > 0;

  // If no yield and no history, this stock doesn't pay dividends — hide card
  if (!hasYield && !hasHistory) return null;

  const maxAmt = hasHistory ? Math.max(...data.history.map((h) => h.amount)) : 1;

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle>Dividends</CardTitle>
          {hasYield && (
            <span className="text-xs tabular-nums text-[var(--color-accent)]">
              {(data.dividend_yield! * 100).toFixed(2)}% yield
            </span>
          )}
        </div>
      </CardHeader>
      <CardContent>
        {/* KPI row */}
        {data.payout_ratio != null && (
          <div className="mb-3 flex items-center gap-4 text-[10px] text-[var(--color-muted)]">
            <span>
              Payout ratio:{" "}
              <span className="text-[var(--color-foreground)] font-medium">
                {(data.payout_ratio * 100).toFixed(1)}%
              </span>
            </span>
          </div>
        )}

        {/* Annual dividend bars */}
        {hasHistory && (
          <div className="space-y-1">
            {data.history.map((h) => {
              const barWidth = Math.min((h.amount / maxAmt) * 100, 100);
              return (
                <div key={h.year} className="flex items-center gap-2">
                  <span className="w-10 shrink-0 text-[10px] tabular-nums text-[var(--color-muted)]">
                    {h.year}
                  </span>
                  <div className="flex-1 h-3 rounded-sm bg-[var(--color-surface)] overflow-hidden">
                    <div
                      className="h-full rounded-sm"
                      style={{
                        width: `${barWidth}%`,
                        backgroundColor: "var(--color-accent)",
                        opacity: 0.7,
                      }}
                    />
                  </div>
                  <span className="w-12 text-right text-[10px] tabular-nums text-[var(--color-foreground)]">
                    ${h.amount.toFixed(2)}
                  </span>
                </div>
              );
            })}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
