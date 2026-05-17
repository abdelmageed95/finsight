"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { ArrowRight, ExternalLink, FileText } from "lucide-react";
import { api } from "@/lib/api";
import { formatCurrency, formatNumber, formatPercent, formatRelativeTime } from "@/lib/utils";
import { Card, CardContent } from "@/components/ui/card";
import { KpiCard } from "@/components/finsight/kpi-card";
import { CandlestickChart, type Candle } from "@/components/finsight/candlestick-chart";
import { FilingTimeline } from "@/components/finsight/filing-timeline";
import { FinancialsTrendChart } from "@/components/finsight/financials-trend-chart";
import { VolatilityCard } from "@/components/finsight/volatility-card";
import { PeerComparison } from "@/components/finsight/peer-comparison";
import { MetricsTrend } from "@/components/finsight/metrics-trend";
import { NewsSentimentCard } from "@/components/finsight/news-sentiment-card";
import { HoldersCard } from "@/components/finsight/holders-card";
import { EarningsCard } from "@/components/finsight/earnings-card";
import { DividendCard } from "@/components/finsight/dividend-card";
import { SuggestedQuestions } from "@/components/finsight/suggested-questions";
import { VerdictChip, riskLevelLabel } from "@/components/finsight/verdict-chip";
import type { TickerResponse } from "@/lib/schemas";

interface Props {
  ticker: string;
  data: TickerResponse;
  onAskInChat: (question: string) => void;
  onOpenResearch: (jobId?: string) => void;
}

/**
 * Live-data only. AI Summary, Key Risks, and per-ticker Report history live
 * in the Research tab — they are NOT duplicated here.
 *
 * The single connection to the Research tab is the "Latest report" tile,
 * which surfaces the verdict + a deep-link instead of inlining the prose.
 */
export function WorkspaceOverview({ ticker, data, onAskInChat, onOpenResearch }: Props) {
  const { data: history } = useQuery({
    queryKey: ["history", ticker],
    queryFn: () => api.history({ ticker, limit: 1 }),
    retry: false,
  });
  const latestJobId = history?.[0]?.job_id;
  const { data: latestReport } = useQuery({
    queryKey: ["report", latestJobId],
    queryFn: () => api.report(latestJobId!),
    enabled: !!latestJobId,
    retry: false,
  });

  const candles: Candle[] = data.prices
    .filter((p) => p.open != null && p.high != null && p.low != null && p.close != null)
    .map((p) => ({
      time: p.date,
      open: p.open!,
      high: p.high!,
      low: p.low!,
      close: p.close!,
      volume: p.volume ?? undefined,
    }));

  return (
    <div className="space-y-8">
      {/* Suggested questions — pre-fill into Chat tab */}
      <SuggestedQuestions
        ticker={ticker}
        onSelect={(question) => onAskInChat(question)}
      />

      {/* Latest-report strip: thin, read-only, links into Research */}
      <LatestReportTile
        ticker={ticker}
        report={latestReport ?? null}
        jobId={latestJobId ?? null}
        onOpen={onOpenResearch}
      />

      {/* KPI row 1 */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <KpiCard label="Market cap" value={formatCurrency(data.market_cap, 2)} />
        <KpiCard
          label="P/E ratio"
          value={formatNumber(data.financials?.pe_ratio ?? null, 2)}
        />
        <KpiCard
          label="Revenue"
          value={formatCurrency(data.financials?.revenue ?? null, 2)}
          hint={data.financials?.period ?? undefined}
        />
        <KpiCard
          label="Net income"
          value={formatCurrency(data.financials?.net_income ?? null, 2)}
          hint={data.financials?.period ?? undefined}
        />
      </div>

      {/* KPI row 2 */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <KpiCard label="EPS" value={formatNumber(data.financials?.eps ?? null, 2)} />
        <KpiCard
          label="Gross margin"
          value={
            data.financials?.gross_margin != null
              ? formatPercent(data.financials.gross_margin * 100, 1)
              : "—"
          }
        />
        <VolatilityCard prices={candles} />
        <KpiCard
          label="Day range"
          value={
            data.day_change != null
              ? `${data.day_change >= 0 ? "+" : ""}${data.day_change.toFixed(2)}`
              : "—"
          }
          hint={
            data.day_change_pct != null
              ? formatPercent(data.day_change_pct)
              : undefined
          }
        />
      </div>

      {/* Candlestick */}
      {candles.length > 0 ? (
        <CandlestickChart data={candles} height={440} />
      ) : (
        <EmptyPriceState />
      )}

      {/* Financial trends */}
      {data.financials_history.length >= 2 && (
        <FinancialsTrendChart data={data.financials_history} />
      )}

      {/* Filings + Peers */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        {data.filings.length > 0 ? (
          <FilingTimeline filings={data.filings} />
        ) : (
          <Card>
            <CardContent className="py-8 text-center text-sm text-[var(--color-muted)]">
              No SEC filings indexed yet for {ticker}.
            </CardContent>
          </Card>
        )}
        <PeerComparison ticker={ticker} />
      </div>

      {/* Metrics trend + News */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <MetricsTrend ticker={ticker} />
        <NewsSentimentCard ticker={ticker} />
      </div>

      {/* Holders + Earnings + Dividends */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <HoldersCard ticker={ticker} />
        <EarningsCard ticker={ticker} />
        <DividendCard ticker={ticker} />
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Latest report tile — links into Research tab instead of inlining the prose
// ---------------------------------------------------------------------------

function LatestReportTile({
  ticker,
  report,
  jobId,
  onOpen,
}: {
  ticker: string;
  report: { summary?: string | null; risk_score?: number | null; valuation_rating?: string | null; confidence?: string | null; generated_at?: string | null } | null;
  jobId: string | null;
  onOpen: (jobId?: string) => void;
}) {
  if (!report) {
    return (
      <Card>
        <CardContent className="flex flex-col items-start gap-3 py-6 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <p className="text-sm font-medium text-[var(--color-foreground)]">
              No research report yet for {ticker}.
            </p>
            <p className="text-xs text-[var(--color-muted)]">
              Click <span className="font-medium text-[var(--color-foreground)]">Generate report</span> in the
              header to run the full RAG pipeline (~30–60s).
            </p>
          </div>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardContent className="flex flex-col gap-4 py-5 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex flex-1 flex-wrap items-center gap-3">
          <FileText className="h-4 w-4 shrink-0 text-[var(--color-accent)]" />
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-xs font-semibold uppercase tracking-wider text-[var(--color-muted)]">
                Latest report
              </span>
              <VerdictChip
                inputs={{
                  risk_score: report.risk_score,
                  valuation_rating: report.valuation_rating,
                  confidence: report.confidence,
                }}
              />
              {report.risk_score != null && (
                <span className="rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] px-2 py-0.5 font-mono text-[10px] uppercase tracking-wider text-[var(--color-muted-strong)]">
                  {riskLevelLabel(report.risk_score)} · {report.risk_score}/100
                </span>
              )}
              <span className="text-[11px] text-[var(--color-muted)]">
                Updated {formatRelativeTime(report.generated_at)}
              </span>
            </div>
            <p className="mt-1.5 line-clamp-1 text-sm text-[var(--color-muted-strong)]">
              {report.summary || "No summary available."}
            </p>
          </div>
        </div>
        <button
          type="button"
          onClick={() => onOpen(jobId ?? undefined)}
          className="inline-flex shrink-0 items-center gap-1.5 rounded-[var(--radius-md)] border border-[var(--color-accent)]/40 bg-[color:color-mix(in_oklab,var(--color-accent)_8%,transparent)] px-3 py-2 text-sm font-medium text-[var(--color-accent)] hover:bg-[color:color-mix(in_oklab,var(--color-accent)_14%,transparent)]"
        >
          Open full report <ArrowRight className="h-3.5 w-3.5" />
        </button>
      </CardContent>
    </Card>
  );
}

function EmptyPriceState() {
  return (
    <Card>
      <CardContent className="py-12 text-center">
        <p className="text-sm text-[var(--color-muted)]">
          No price history available yet.
        </p>
        <Link
          href="https://www.sec.gov/edgar.shtml"
          target="_blank"
          className="mt-2 inline-flex items-center gap-1 text-xs text-[var(--color-muted)] hover:text-[var(--color-accent)]"
        >
          SEC EDGAR <ExternalLink className="h-3 w-3" />
        </Link>
      </CardContent>
    </Card>
  );
}
