"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { api } from "@/lib/api";
import { cn, formatCurrency, formatNumber, formatPercent } from "@/lib/utils";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

interface PeerInfo {
  symbol: string;
  company_name: string;
  price: number | null;
  market_cap: number | null;
  pe_ratio: number | null;
  gross_margin: number | null;
  day_change_pct: number | null;
}

interface PeersResponse {
  ticker: string;
  sector: string;
  current: PeerInfo | null;
  peers: PeerInfo[];
}

export function PeerComparison({ ticker }: { ticker: string }) {
  const { data, isLoading } = useQuery({
    queryKey: ["peers", ticker],
    queryFn: () => api.peers(ticker) as Promise<PeersResponse>,
    retry: false,
    staleTime: 1000 * 60 * 15, // 15 min
  });

  if (isLoading || !data || data.peers.length === 0) return null;

  const all = [
    ...(data.current ? [data.current] : []),
    ...data.peers,
  ];

  return (
    <Card>
      <CardHeader>
        <CardTitle>
          Sector peers
          {data.sector && (
            <span className="ml-2 text-xs font-normal text-[var(--color-muted)]">
              {data.sector}
            </span>
          )}
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-[var(--color-border)] text-left text-[10px] uppercase tracking-wider text-[var(--color-muted)]">
                <th className="pb-2 pr-4 font-medium">Ticker</th>
                <th className="pb-2 pr-4 font-medium">Price</th>
                <th className="pb-2 pr-4 font-medium">Market Cap</th>
                <th className="pb-2 pr-4 font-medium">P/E</th>
                <th className="pb-2 pr-4 font-medium">Margin</th>
                <th className="pb-2 font-medium">Day</th>
              </tr>
            </thead>
            <tbody>
              {all.map((p) => {
                const isCurrent = p.symbol === data.ticker;
                const dayPct = p.day_change_pct;
                return (
                  <tr
                    key={p.symbol}
                    className={cn(
                      "border-b border-[var(--color-border)] last:border-0",
                      isCurrent && "bg-[color:color-mix(in_oklab,var(--color-accent)_5%,transparent)]"
                    )}
                  >
                    <td className="py-2 pr-4">
                      <Link
                        href={`/workspace/${p.symbol}`}
                        className={cn(
                          "font-mono text-xs font-medium hover:text-[var(--color-accent)]",
                          isCurrent
                            ? "text-[var(--color-accent)]"
                            : "text-[var(--color-foreground)]"
                        )}
                      >
                        {p.symbol}
                      </Link>
                      <span className="ml-1.5 text-[10px] text-[var(--color-muted)]">
                        {(p.company_name ?? "").length > 20
                          ? p.company_name?.slice(0, 20) + "…"
                          : p.company_name}
                      </span>
                    </td>
                    <td className="py-2 pr-4 font-mono text-xs tabular-nums text-[var(--color-foreground)]">
                      {p.price != null ? formatCurrency(p.price, 2) : "—"}
                    </td>
                    <td className="py-2 pr-4 font-mono text-xs tabular-nums text-[var(--color-foreground)]">
                      {p.market_cap != null ? formatCurrency(p.market_cap, 0) : "—"}
                    </td>
                    <td className="py-2 pr-4 font-mono text-xs tabular-nums text-[var(--color-foreground)]">
                      {p.pe_ratio != null ? formatNumber(p.pe_ratio, 1) : "—"}
                    </td>
                    <td className="py-2 pr-4 font-mono text-xs tabular-nums text-[var(--color-foreground)]">
                      {p.gross_margin != null
                        ? formatPercent(p.gross_margin * 100, 1)
                        : "—"}
                    </td>
                    <td
                      className={cn(
                        "py-2 font-mono text-xs tabular-nums",
                        dayPct != null && dayPct >= 0
                          ? "text-[var(--color-accent)]"
                          : "text-[var(--color-danger)]"
                      )}
                    >
                      {dayPct != null
                        ? `${dayPct >= 0 ? "+" : ""}${dayPct.toFixed(2)}%`
                        : "—"}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </CardContent>
    </Card>
  );
}
