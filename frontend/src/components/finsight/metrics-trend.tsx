"use client";

import { useQuery } from "@tanstack/react-query";
import { formatRelativeTime } from "@/lib/utils";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { z } from "zod";

const metricsTrendSchema = z.object({
  ticker: z.string(),
  trend: z.array(
    z.object({
      job_id: z.string(),
      date: z.string().nullable(),
      risk_score: z.number().nullable(),
      metrics: z.record(z.string(), z.string()),
    })
  ),
});

async function fetchMetricsTrend(ticker: string) {
  // Use raw fetch since this isn't in api.ts yet with proper typing
  const token = (await import("@/lib/auth")).getToken();
  const base = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
  const res = await fetch(`${base}/history/${encodeURIComponent(ticker)}/metrics`, {
    headers: {
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
  });
  if (!res.ok) return null;
  const data = await res.json();
  return metricsTrendSchema.parse(data);
}

export function MetricsTrend({ ticker }: { ticker: string }) {
  const { data } = useQuery({
    queryKey: ["metrics-trend", ticker],
    queryFn: () => fetchMetricsTrend(ticker),
    retry: false,
  });

  if (!data || data.trend.length < 2) return null;

  // Collect all unique metric names
  const allNames = new Set<string>();
  for (const entry of data.trend) {
    for (const name of Object.keys(entry.metrics)) allNames.add(name);
  }
  const metricNames = Array.from(allNames);

  return (
    <Card>
      <CardHeader>
        <CardTitle>Metrics across analyses</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-[var(--color-border)] text-left text-[10px] uppercase tracking-wider text-[var(--color-muted)]">
                <th className="pb-2 pr-4 font-medium">Metric</th>
                {data.trend.map((entry) => (
                  <th key={entry.job_id} className="pb-2 pr-4 font-medium">
                    {entry.date ? formatRelativeTime(entry.date) : "—"}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {/* Risk score row */}
              <tr className="border-b border-[var(--color-border)]">
                <td className="py-2 pr-4 text-xs text-[var(--color-muted-strong)]">
                  Risk Score
                </td>
                {data.trend.map((entry) => (
                  <td
                    key={entry.job_id}
                    className="py-2 pr-4 font-mono text-xs tabular-nums text-[var(--color-foreground)]"
                  >
                    {entry.risk_score ?? "—"}
                  </td>
                ))}
              </tr>
              {metricNames.map((name) => (
                <tr key={name} className="border-b border-[var(--color-border)] last:border-0">
                  <td className="py-2 pr-4 text-xs text-[var(--color-muted-strong)]">
                    {name}
                  </td>
                  {data.trend.map((entry) => (
                    <td
                      key={entry.job_id}
                      className="py-2 pr-4 font-mono text-xs tabular-nums text-[var(--color-foreground)]"
                    >
                      {entry.metrics[name] ?? "—"}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </CardContent>
    </Card>
  );
}
