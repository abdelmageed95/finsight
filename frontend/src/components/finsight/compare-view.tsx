"use client";

import { useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { ArrowRight, GitCompareArrows, Loader2, Trophy } from "lucide-react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";

interface MetricComparison {
  metric: string;
  ticker_a_value: string;
  ticker_b_value: string;
  winner: string;
  context: string;
}

interface ComparisonData {
  job_id: string;
  status: string;
  ticker_a: string | null;
  ticker_b: string | null;
  summary: string | null;
  metric_comparisons: MetricComparison[] | null;
  recommendation: string | null;
  generated_at: string | null;
}

const STORAGE_KEY = "finsight.lastComparison";

function loadLastComparison(): { tickerA: string; tickerB: string; jobId: string } | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    if (parsed.tickerA && parsed.tickerB && parsed.jobId) return parsed;
  } catch { /* ignore */ }
  return null;
}

function saveLastComparison(tickerA: string, tickerB: string, jobId: string) {
  if (typeof window === "undefined") return;
  localStorage.setItem(STORAGE_KEY, JSON.stringify({ tickerA, tickerB, jobId }));
}

export function CompareView() {
  const searchParams = useSearchParams();
  const last = loadLastComparison();
  const queryA = searchParams.get("a")?.toUpperCase() ?? "";
  const queryB = searchParams.get("b")?.toUpperCase() ?? "";
  const [tickerA, setTickerA] = useState(queryA || last?.tickerA || "");
  const [tickerB, setTickerB] = useState(queryB || last?.tickerB || "");
  // Only restore the cached job if we didn't arrive with explicit query params
  const restoredJob = !queryA && !queryB ? last?.jobId ?? null : null;
  const [jobId, setJobId] = useState<string | null>(restoredJob);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // If the URL changes (e.g. user clicks "Compare to…" again from another
  // dashboard), update the inputs and reset any stale job result.
  useEffect(() => {
    if (queryA) setTickerA(queryA);
    if (queryB) setTickerB(queryB);
    if (queryA && queryB) setJobId(null);
  }, [queryA, queryB]);

  const { data } = useQuery({
    queryKey: ["comparison", jobId],
    queryFn: () => api.comparisonReport(jobId!) as Promise<ComparisonData>,
    enabled: !!jobId,
    refetchInterval: (query) => {
      const status = (query.state.data as ComparisonData | undefined)?.status;
      return status === "pending" || status === "running" ? 3000 : false;
    },
  });

  async function startComparison() {
    if (!tickerA.trim() || !tickerB.trim()) return;
    setError(null);
    setLoading(true);
    try {
      const res = await api.compare(tickerA.trim(), tickerB.trim());
      setJobId(res.job_id);
      saveLastComparison(tickerA.trim(), tickerB.trim(), res.job_id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Comparison failed");
    } finally {
      setLoading(false);
    }
  }

  const completed = data?.status === "completed";
  const running = data?.status === "pending" || data?.status === "running";

  return (
    <div className="flex flex-1 flex-col">
      <header className="border-b border-[var(--color-border)] px-6 py-4">
        <div className="mx-auto flex w-full max-w-5xl items-center gap-3">
          <GitCompareArrows className="h-5 w-5 text-[var(--color-accent)]" />
          <h1 className="text-lg font-semibold text-[var(--color-foreground)]">
            Compare stocks
          </h1>
        </div>
      </header>

      <main className="mx-auto w-full max-w-5xl flex-1 px-6 py-10">
        {/* Input form */}
        <div className="mb-8 flex flex-wrap items-end gap-3">
          <div>
            <label className="mb-1 block text-[10px] uppercase tracking-wider text-[var(--color-muted)]">
              Ticker A
            </label>
            <input
              type="text"
              value={tickerA}
              onChange={(e) => setTickerA(e.target.value.toUpperCase())}
              placeholder="AAPL"
              className="h-10 w-28 rounded-[var(--radius-md)] border border-[var(--color-border)] bg-[var(--color-surface)] px-3 font-mono text-sm text-[var(--color-foreground)] placeholder:text-[var(--color-muted)] focus:border-[var(--color-accent)] focus:outline-none"
            />
          </div>
          <span className="mb-2 text-sm text-[var(--color-muted)]">vs</span>
          <div>
            <label className="mb-1 block text-[10px] uppercase tracking-wider text-[var(--color-muted)]">
              Ticker B
            </label>
            <input
              type="text"
              value={tickerB}
              onChange={(e) => setTickerB(e.target.value.toUpperCase())}
              placeholder="MSFT"
              className="h-10 w-28 rounded-[var(--radius-md)] border border-[var(--color-border)] bg-[var(--color-surface)] px-3 font-mono text-sm text-[var(--color-foreground)] placeholder:text-[var(--color-muted)] focus:border-[var(--color-accent)] focus:outline-none"
            />
          </div>
          <Button
            variant="primary"
            size="md"
            onClick={startComparison}
            disabled={loading || !tickerA.trim() || !tickerB.trim()}
          >
            {loading ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <ArrowRight className="h-4 w-4" />
            )}
            Compare
          </Button>
        </div>

        {error && (
          <Card className="mb-6 border-[color:color-mix(in_oklab,var(--color-danger)_40%,transparent)]">
            <CardContent className="p-4 text-sm text-[var(--color-danger)]">
              {error}
            </CardContent>
          </Card>
        )}

        {running && (
          <Card className="mb-6">
            <CardContent className="flex items-center gap-3 p-6 text-sm text-[var(--color-muted)]">
              <Loader2 className="h-4 w-4 animate-spin" />
              Generating comparison… This may take a moment.
            </CardContent>
          </Card>
        )}

        {completed && data && (
          <>
            {/* Summary */}
            {data.summary && (
              <section className="mb-8">
                <h2 className="mb-3 text-xs font-medium uppercase tracking-wider text-[var(--color-muted)]">
                  Comparative analysis
                </h2>
                <p className="text-base leading-relaxed text-[var(--color-foreground)]">
                  {data.summary}
                </p>
              </section>
            )}

            <Separator className="my-8" />

            {/* Metric comparison table */}
            {data.metric_comparisons && data.metric_comparisons.length > 0 && (
              <section className="mb-8">
                <h2 className="mb-4 text-xs font-medium uppercase tracking-wider text-[var(--color-muted)]">
                  Head-to-head metrics
                </h2>
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-[var(--color-border)] text-[10px] uppercase tracking-wider text-[var(--color-muted)]">
                        <th className="pb-2 text-left font-medium">Metric</th>
                        <th className="pb-2 text-right font-medium">{data.ticker_a}</th>
                        <th className="pb-2 text-right font-medium">{data.ticker_b}</th>
                        <th className="pb-2 text-center font-medium">Winner</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.metric_comparisons.map((mc, i) => (
                        <tr
                          key={i}
                          className="border-b border-[var(--color-border)] last:border-0"
                        >
                          <td className="py-2.5 pr-4 text-[var(--color-foreground)] font-medium">
                            {mc.metric}
                          </td>
                          <td
                            className="py-2.5 text-right tabular-nums"
                            style={{
                              color:
                                mc.winner === data.ticker_a
                                  ? "var(--color-accent)"
                                  : "var(--color-muted-strong)",
                              fontWeight: mc.winner === data.ticker_a ? 600 : 400,
                            }}
                          >
                            {mc.ticker_a_value}
                          </td>
                          <td
                            className="py-2.5 text-right tabular-nums"
                            style={{
                              color:
                                mc.winner === data.ticker_b
                                  ? "var(--color-accent)"
                                  : "var(--color-muted-strong)",
                              fontWeight: mc.winner === data.ticker_b ? 600 : 400,
                            }}
                          >
                            {mc.ticker_b_value}
                          </td>
                          <td className="py-2.5 text-center">
                            {mc.winner.toLowerCase() === "tie" ? (
                              <span className="text-xs text-[var(--color-muted)]">Tie</span>
                            ) : (
                              <span className="inline-flex items-center gap-1 text-xs font-semibold text-[var(--color-accent)]">
                                <Trophy className="h-3 w-3" />
                                {mc.winner}
                              </span>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </section>
            )}

            {/* Recommendation */}
            {data.recommendation && (
              <>
                <Separator className="my-8" />
                <section>
                  <h2 className="mb-3 text-xs font-medium uppercase tracking-wider text-[var(--color-muted)]">
                    Recommendation
                  </h2>
                  <Card>
                    <CardContent className="p-5">
                      <p className="text-sm leading-relaxed text-[var(--color-foreground)]">
                        {data.recommendation}
                      </p>
                    </CardContent>
                  </Card>
                </section>
              </>
            )}
          </>
        )}

        {/* Empty state */}
        {!jobId && !loading && (
          <div className="mt-16 text-center">
            <GitCompareArrows className="mx-auto h-12 w-12 text-[var(--color-muted)]" />
            <p className="mt-4 text-sm text-[var(--color-muted-strong)]">
              Enter two ticker symbols to generate a side-by-side comparison.
            </p>
            <p className="mt-1 text-xs text-[var(--color-muted)]">
              Both tickers should have existing analysis reports for best results.
            </p>
          </div>
        )}
      </main>
    </div>
  );
}
