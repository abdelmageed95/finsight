"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

interface Holder {
  holder: string;
  shares: number | null;
  date_reported: string;
  pct_out: number | null;
  value: number | null;
}

interface HoldersResponse {
  ticker: string;
  holders: Holder[];
}

function fmtNum(n: number | null): string {
  if (n == null) return "—";
  if (n >= 1e9) return `${(n / 1e9).toFixed(1)}B`;
  if (n >= 1e6) return `${(n / 1e6).toFixed(1)}M`;
  if (n >= 1e3) return `${(n / 1e3).toFixed(1)}K`;
  return n.toLocaleString();
}

export function HoldersCard({ ticker }: { ticker: string }) {
  const { data } = useQuery({
    queryKey: ["holders", ticker],
    queryFn: () => api.holders(ticker) as Promise<HoldersResponse>,
    retry: false,
    staleTime: 1000 * 60 * 30,
  });

  if (!data || data.holders.length === 0) return null;

  return (
    <Card>
      <CardHeader>
        <CardTitle>Top institutional holders</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-[var(--color-border)] text-[10px] uppercase tracking-wider text-[var(--color-muted)]">
                <th className="pb-2 text-left font-medium">Holder</th>
                <th className="pb-2 text-right font-medium">Shares</th>
                <th className="pb-2 text-right font-medium">% Out</th>
                <th className="pb-2 text-right font-medium">Value</th>
              </tr>
            </thead>
            <tbody>
              {data.holders.map((h, i) => (
                <tr
                  key={i}
                  className="border-b border-[var(--color-border)] last:border-0"
                >
                  <td className="py-1.5 pr-3 text-[var(--color-foreground)] truncate max-w-[180px]">
                    {h.holder}
                  </td>
                  <td className="py-1.5 text-right tabular-nums text-[var(--color-muted)]">
                    {fmtNum(h.shares)}
                  </td>
                  <td className="py-1.5 text-right tabular-nums text-[var(--color-muted)]">
                    {h.pct_out != null ? `${(h.pct_out * 100).toFixed(2)}%` : "—"}
                  </td>
                  <td className="py-1.5 text-right tabular-nums text-[var(--color-muted)]">
                    ${fmtNum(h.value)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </CardContent>
    </Card>
  );
}
