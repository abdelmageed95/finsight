"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { useRef, useCallback, useState } from "react";
import {
  ArrowLeft,
  ChevronDown,
  ChevronRight,
  Copy,
  Download,
  ExternalLink,
  FileText,
  MessageSquare,
  RefreshCw,
  Share2,
  Shield,
  Sparkles,
  Target,
  TrendingDown,
  TrendingUp,
  Users,
  Zap,
} from "lucide-react";
import { api } from "@/lib/api";
import { cn, formatCurrency, formatRelativeTime } from "@/lib/utils";
import { RiskGauge } from "./risk-gauge";
import { StatusBadge } from "./status-badge";
import { VerdictChip } from "./verdict-chip";
import { CitationText } from "./citation-popover";
import { StarButton } from "./star-button";
import type { ReportCitation } from "@/lib/schemas";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";

// ---------------------------------------------------------------------------
// Section IDs for Table of Contents
// ---------------------------------------------------------------------------
const SECTIONS = [
  { id: "executive-summary", label: "Executive Summary" },
  { id: "summary", label: "Analysis" },
  { id: "risk", label: "Risk Assessment" },
  { id: "swot", label: "SWOT" },
  { id: "thesis", label: "Bull vs Bear" },
  { id: "moat", label: "Competitive Moat" },
  { id: "revenue", label: "Revenue Segments" },
  { id: "valuation", label: "Valuation" },
  { id: "catalysts", label: "Catalysts" },
  { id: "management", label: "Management" },
  { id: "metrics", label: "Key Metrics" },
  { id: "market-context", label: "Market Context" },
  { id: "sources", label: "Sources" },
  { id: "follow-up", label: "Next Steps" },
] as const;

// ---------------------------------------------------------------------------
// Collapsible section wrapper
// ---------------------------------------------------------------------------
function Section({
  id,
  title,
  children,
  defaultOpen = true,
}: {
  id: string;
  title: string;
  children: React.ReactNode;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <section id={id} className="mb-10 scroll-mt-20">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="mb-4 flex w-full items-center gap-2 text-left"
      >
        {open ? (
          <ChevronDown className="h-3.5 w-3.5 text-[var(--color-muted)]" />
        ) : (
          <ChevronRight className="h-3.5 w-3.5 text-[var(--color-muted)]" />
        )}
        <h2 className="text-xs font-medium uppercase tracking-wider text-[var(--color-muted)]">
          {title}
        </h2>
      </button>
      {open && children}
    </section>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------
export function ReportDetailView({ jobId }: { jobId: string }) {
  const reportRef = useRef<HTMLDivElement>(null);

  const { data, isLoading, refetch } = useQuery({
    queryKey: ["report", jobId],
    queryFn: () => api.report(jobId),
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === "pending" || status === "running" ? 3000 : false;
    },
  });

  const ticker = data?.ticker ?? "";

  // Live data queries (only when report is completed and has a ticker)
  const { data: tickerData } = useQuery({
    queryKey: ["ticker", ticker],
    queryFn: () => api.ticker(ticker),
    enabled: !!ticker && data?.status === "completed",
    retry: false,
    staleTime: 1000 * 60 * 5,
  });

  const { data: newsData } = useQuery({
    queryKey: ["news", ticker],
    queryFn: () => api.news(ticker) as Promise<{ articles: Array<{ title: string; url: string; source: string; published_at: string; sentiment_score: number | null }> }>,
    enabled: !!ticker && data?.status === "completed",
    retry: false,
    staleTime: 1000 * 60 * 15,
  });

  const { data: peersData } = useQuery({
    queryKey: ["peers", ticker],
    queryFn: () => api.peers(ticker) as Promise<{ ticker: string; peers: Array<{ symbol: string; company_name: string; price: number | null; market_cap: number | null; pe_ratio: number | null; gross_margin: number | null; day_change_pct: number | null }> }>,
    enabled: !!ticker && data?.status === "completed",
    retry: false,
    staleTime: 1000 * 60 * 15,
  });

  // PDF export
  const downloadPdf = useCallback(async () => {
    const el = reportRef.current;
    if (!el) return;
    const [{ default: html2canvas }, { jsPDF }] = await Promise.all([
      import("html2canvas-pro"),
      import("jspdf"),
    ]);
    const canvas = await html2canvas(el, { scale: 2, useCORS: true, backgroundColor: "#09090b" });
    const imgData = canvas.toDataURL("image/png");
    const pdf = new jsPDF({ orientation: "portrait", unit: "mm", format: "a4" });
    const pageW = pdf.internal.pageSize.getWidth();
    const pageH = pdf.internal.pageSize.getHeight();
    const imgW = pageW - 20;
    const imgH = (canvas.height * imgW) / canvas.width;

    if (imgH <= pageH - 20) {
      pdf.addImage(imgData, "PNG", 10, 10, imgW, imgH);
    } else {
      const pageContentH = pageH - 20;
      let srcY = 0;
      let remainingH = imgH;
      while (remainingH > 0) {
        const sliceH = Math.min(pageContentH, remainingH);
        const sliceCanvas = document.createElement("canvas");
        sliceCanvas.width = canvas.width;
        sliceCanvas.height = (sliceH / imgH) * canvas.height;
        const ctx = sliceCanvas.getContext("2d")!;
        ctx.drawImage(canvas, 0, srcY, canvas.width, sliceCanvas.height, 0, 0, canvas.width, sliceCanvas.height);
        if (srcY > 0) pdf.addPage();
        pdf.addImage(sliceCanvas.toDataURL("image/png"), "PNG", 10, 10, imgW, sliceH);
        srcY += sliceCanvas.height;
        remainingH -= sliceH;
      }
    }
    pdf.save(`finsight-${ticker || "report"}-${jobId.slice(0, 8)}.pdf`);
  }, [ticker, jobId]);

  // Share as image (captures a summary card)
  const shareAsImage = useCallback(async () => {
    const el = document.getElementById("executive-summary");
    if (!el) return;
    const { default: html2canvas } = await import("html2canvas-pro");
    const canvas = await html2canvas(el, { scale: 2, useCORS: true, backgroundColor: "#09090b" });
    canvas.toBlob(async (blob) => {
      if (!blob) return;
      if (navigator.share && navigator.canShare?.({ files: [new File([blob], "report.png")] })) {
        await navigator.share({
          title: `FinSight — ${ticker}`,
          files: [new File([blob], `finsight-${ticker}.png`, { type: "image/png" })],
        });
      } else {
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = `finsight-${ticker}-summary.png`;
        a.click();
        URL.revokeObjectURL(url);
      }
    });
  }, [ticker]);

  if (isLoading || !data) {
    return (
      <div className="flex flex-1 items-center justify-center p-10 text-sm text-[var(--color-muted)]">
        Loading report...
      </div>
    );
  }

  async function copyLink() {
    const url = window.location.href;
    // navigator.clipboard only exists in a secure context (HTTPS/localhost),
    // so it is undefined behind an HTTP-only ALB. Fall back to a hidden
    // textarea + execCommand("copy") which works over plain http://.
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(url);
      return;
    }
    const ta = document.createElement("textarea");
    ta.value = url;
    ta.style.position = "fixed";
    ta.style.opacity = "0";
    document.body.appendChild(ta);
    ta.select();
    try {
      document.execCommand("copy");
    } finally {
      document.body.removeChild(ta);
    }
  }

  function downloadJson() {
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `finsight-${ticker || "report"}-${jobId.slice(0, 8)}.json`;
    a.click();
    URL.revokeObjectURL(url);
  }

  const pending = data.status === "pending" || data.status === "running";
  const positive = (tickerData?.day_change ?? 0) >= 0;

  // Visible sections for TOC
  const visibleSections = SECTIONS.filter((s) => {
    if (s.id === "executive-summary") return !!data.executive_summary;
    if (s.id === "swot") return !!data.swot;
    if (s.id === "thesis") return !!(data.bull_case || data.bear_case);
    if (s.id === "moat") return !!data.competitive_moat;
    if (s.id === "revenue") return data.revenue_segments && data.revenue_segments.length > 0;
    if (s.id === "valuation") return !!data.valuation_verdict;
    if (s.id === "catalysts") return data.catalysts && data.catalysts.length > 0;
    if (s.id === "management") return !!data.management_assessment;
    if (s.id === "metrics") return data.key_metrics && data.key_metrics.length > 0;
    if (s.id === "sources") return data.citations && data.citations.length > 0;
    return data.status === "completed";
  });

  return (
    <div className="flex flex-1 flex-col">
      {/* Header */}
      <header className="border-b border-[var(--color-border)] px-6 py-4">
        <div className="mx-auto flex w-full max-w-6xl items-center justify-between">
          <Link
            href="/home"
            className="inline-flex items-center gap-1.5 text-sm text-[var(--color-muted-strong)] hover:text-[var(--color-foreground)]"
          >
            <ArrowLeft className="h-4 w-4" />
            Home
          </Link>
          <div className="flex items-center gap-2">
            <StarButton jobId={data.job_id} starred={data.is_starred ?? false} size="md" />
            <StatusBadge status={data.status} />
          </div>
        </div>
      </header>

      <div className="mx-auto flex w-full max-w-6xl flex-1 gap-0 lg:gap-8">
        {/* Sticky TOC sidebar */}
        {data.status === "completed" && visibleSections.length > 3 && (
          <aside className="hidden lg:block lg:w-48 shrink-0 pt-10">
            <nav className="sticky top-24 space-y-1">
              <p className="mb-3 text-[10px] font-medium uppercase tracking-wider text-[var(--color-muted)]">
                Contents
              </p>
              {visibleSections.map((s) => (
                <a
                  key={s.id}
                  href={`#${s.id}`}
                  className="block rounded-[var(--radius-sm)] px-2 py-1 text-xs text-[var(--color-muted-strong)] transition-colors hover:bg-[var(--color-surface)] hover:text-[var(--color-foreground)]"
                >
                  {s.label}
                </a>
              ))}
            </nav>
          </aside>
        )}

        {/* Main content */}
        <main ref={reportRef} className="flex-1 min-w-0 px-6 py-10">
          {/* Title + actions */}
          <div className="mb-8 flex items-start justify-between gap-6">
            <div>
              <div className="mb-2 flex items-baseline gap-3">
                <Link href={`/workspace/${ticker}`} className="font-mono text-4xl font-semibold tracking-wide text-[var(--color-foreground)] hover:text-[var(--color-accent)]">
                  {ticker}
                </Link>
              </div>
              <p className="text-lg text-[var(--color-muted-strong)]">
                {data.question ?? "Research report"}
              </p>
              <p className="mt-3 text-xs text-[var(--color-muted)]">
                Generated {formatRelativeTime(data.generated_at ?? null)}
                {data.confidence && ` · Confidence: ${data.confidence}`}
              </p>
            </div>
            <div className="flex shrink-0 flex-col gap-2">
              <Button variant="secondary" size="sm" onClick={downloadPdf}>
                <FileText className="h-4 w-4" /> PDF
              </Button>
              <Button variant="secondary" size="sm" onClick={shareAsImage}>
                <Share2 className="h-4 w-4" /> Share
              </Button>
              <Button variant="secondary" size="sm" onClick={downloadJson}>
                <Download className="h-4 w-4" /> JSON
              </Button>
              <Button variant="secondary" size="sm" onClick={copyLink}>
                <Copy className="h-4 w-4" /> Link
              </Button>
              <Button variant="ghost" size="sm" onClick={() => refetch()}>
                <RefreshCw className="h-4 w-4" /> Refresh
              </Button>
            </div>
          </div>

          {/* Price snapshot strip */}
          {tickerData && data.status === "completed" && (
            <div className="mb-8 flex flex-wrap items-center gap-6 rounded-[var(--radius-md)] border border-[var(--color-border)] bg-[var(--color-surface)]/40 px-5 py-3">
              <div>
                <span className="text-[10px] uppercase tracking-wider text-[var(--color-muted)]">Price</span>
                <p className="font-mono text-lg font-semibold tabular-nums text-[var(--color-foreground)]">
                  {formatCurrency(tickerData.latest_price, 2)}
                </p>
              </div>
              <div>
                <span className="text-[10px] uppercase tracking-wider text-[var(--color-muted)]">Day</span>
                <p className={cn("font-mono text-sm font-medium tabular-nums", positive ? "text-[var(--color-accent)]" : "text-[var(--color-danger)]")}>
                  {positive ? "+" : ""}{tickerData.day_change?.toFixed(2)} ({tickerData.day_change_pct != null ? `${tickerData.day_change_pct.toFixed(2)}%` : "—"})
                </p>
              </div>
              <div>
                <span className="text-[10px] uppercase tracking-wider text-[var(--color-muted)]">Mkt Cap</span>
                <p className="font-mono text-sm tabular-nums text-[var(--color-foreground)]">{formatCurrency(tickerData.market_cap, 2)}</p>
              </div>
              <div>
                <span className="text-[10px] uppercase tracking-wider text-[var(--color-muted)]">P/E</span>
                <p className="font-mono text-sm tabular-nums text-[var(--color-foreground)]">{tickerData.financials?.pe_ratio?.toFixed(1) ?? "—"}</p>
              </div>
              {/* Mini sparkline */}
              {tickerData.prices.length > 5 && (
                <div className="ml-auto">
                  <MiniSparkline prices={tickerData.prices.slice(-30)} positive={positive} />
                </div>
              )}
            </div>
          )}

          {pending && (
            <Card className="mb-8">
              <CardContent className="p-6 text-center text-sm text-[var(--color-muted)]">
                Report is still processing. This page will auto-refresh when ready.
              </CardContent>
            </Card>
          )}

          {data.status === "failed" && (
            <Card className="mb-8 border-[color:color-mix(in_oklab,var(--color-danger)_40%,transparent)]">
              <CardContent className="p-6 text-sm text-[var(--color-danger)]">
                Report failed to generate. Try re-running from the dashboard.
              </CardContent>
            </Card>
          )}

          {data.status === "completed" && (
            <>
              {/* Executive Summary */}
              {data.executive_summary && (
                <div
                  id="executive-summary"
                  className="mb-10 scroll-mt-20 rounded-[var(--radius-lg)] border border-[var(--color-accent)]/20 bg-[var(--color-accent)]/5 p-6"
                >
                  <div className="mb-2 flex flex-wrap items-center justify-between gap-3">
                    <div className="flex items-center gap-2">
                      <Sparkles className="h-4 w-4 text-[var(--color-accent)]" />
                      <span className="text-xs font-semibold uppercase tracking-wider text-[var(--color-accent)]">
                        Executive Summary
                      </span>
                    </div>
                    <VerdictChip
                      size="md"
                      inputs={{
                        risk_score: data.risk_score,
                        valuation_rating: data.valuation_rating,
                        confidence: data.confidence,
                      }}
                    />
                  </div>
                  <p className="text-base font-medium leading-relaxed text-[var(--color-foreground)]">
                    <CitationText
                      text={data.executive_summary}
                      citations={data.citations as ReportCitation[] | null | undefined}
                    />
                  </p>
                </div>
              )}

              {/* Analysis */}
              {data.summary && (
                <Section id="summary" title="Analysis">
                  <p className="text-base leading-relaxed text-[var(--color-foreground)]">
                    <CitationText
                      text={data.summary}
                      citations={data.citations as ReportCitation[] | null | undefined}
                    />
                  </p>
                </Section>
              )}

              <Separator className="my-8" />

              {/* Risk assessment */}
              <Section id="risk" title="Risk assessment">
                <div className="grid grid-cols-1 gap-8 md:grid-cols-[auto_1fr] md:items-center">
                  <div className="flex justify-center md:justify-start">
                    <RiskGauge score={data.risk_score ?? null} size={200} />
                  </div>
                  <div>
                    {data.risk_level && (
                      <p className="mb-3 text-sm font-medium text-[var(--color-foreground)]">{data.risk_level}</p>
                    )}
                    <p className="text-sm leading-relaxed text-[var(--color-muted-strong)]">{data.risk_rationale ?? "—"}</p>
                  </div>
                </div>
                {/* Sub-scores */}
                {data.risk_breakdown && data.risk_breakdown.length > 0 && (
                  <div className="mt-6 space-y-4">
                    {data.risk_breakdown.map((rb, i) => {
                      const score = rb?.score ?? 0;
                      const category = rb?.category ?? "";
                      const rationale = rb?.rationale ?? "";
                      const color = score < 30 ? "var(--color-accent)" : score < 60 ? "var(--color-warning)" : "var(--color-danger)";
                      return (
                        <div key={i}>
                          <div className="mb-1 flex items-baseline justify-between">
                            <span className="text-sm font-medium capitalize text-[var(--color-foreground)]">{category}</span>
                            <span className="font-mono text-sm font-semibold" style={{ color }}>{score}</span>
                          </div>
                          <div className="h-2 w-full rounded-full bg-[var(--color-surface)]">
                            <div className="h-full rounded-full transition-all" style={{ width: `${score}%`, backgroundColor: color }} />
                          </div>
                          {rationale && <p className="mt-1 text-xs text-[var(--color-muted)]">{rationale}</p>}
                        </div>
                      );
                    })}
                  </div>
                )}
              </Section>

              <Separator className="my-8" />

              {/* SWOT */}
              {data.swot && (
                <>
                  <Section id="swot" title="SWOT Analysis">
                    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                      <SwotQuadrant title="Strengths" items={data.swot.strengths} color="var(--color-accent)" />
                      <SwotQuadrant title="Weaknesses" items={data.swot.weaknesses} color="var(--color-danger)" />
                      <SwotQuadrant title="Opportunities" items={data.swot.opportunities} color="#3b82f6" />
                      <SwotQuadrant title="Threats" items={data.swot.threats} color="var(--color-warning)" />
                    </div>
                  </Section>
                  <Separator className="my-8" />
                </>
              )}

              {/* Bull vs Bear */}
              {(data.bull_case || data.bear_case) && (
                <>
                  <Section id="thesis" title="Investment thesis">
                    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                      {data.bull_case && (
                        <div className="rounded-[var(--radius-md)] border p-5" style={{ borderColor: "color-mix(in oklab, var(--color-accent) 40%, transparent)", backgroundColor: "color-mix(in oklab, var(--color-accent) 5%, transparent)" }}>
                          <div className="mb-3 flex items-center gap-2">
                            <TrendingUp className="h-4 w-4 text-[var(--color-accent)]" />
                            <span className="text-sm font-semibold text-[var(--color-accent)]">Bull case</span>
                          </div>
                          <p className="text-sm leading-relaxed text-[var(--color-foreground)]">
                            <CitationText
                              text={data.bull_case}
                              citations={data.citations as ReportCitation[] | null | undefined}
                            />
                          </p>
                        </div>
                      )}
                      {data.bear_case && (
                        <div className="rounded-[var(--radius-md)] border p-5" style={{ borderColor: "color-mix(in oklab, var(--color-danger) 40%, transparent)", backgroundColor: "color-mix(in oklab, var(--color-danger) 5%, transparent)" }}>
                          <div className="mb-3 flex items-center gap-2">
                            <TrendingDown className="h-4 w-4 text-[var(--color-danger)]" />
                            <span className="text-sm font-semibold text-[var(--color-danger)]">Bear case</span>
                          </div>
                          <p className="text-sm leading-relaxed text-[var(--color-foreground)]">
                            <CitationText
                              text={data.bear_case}
                              citations={data.citations as ReportCitation[] | null | undefined}
                            />
                          </p>
                        </div>
                      )}
                    </div>
                  </Section>
                  <Separator className="my-8" />
                </>
              )}

              {/* Competitive Moat */}
              {data.competitive_moat && (
                <>
                  <Section id="moat" title="Competitive moat">
                    <Card>
                      <CardContent className="p-5">
                        <div className="mb-3 flex items-center gap-3">
                          <Shield className="h-5 w-5 text-[var(--color-accent)]" />
                          {data.moat_rating && data.moat_rating !== "unknown" && (
                            <span className={cn(
                              "rounded-full px-2.5 py-0.5 text-xs font-semibold uppercase",
                              data.moat_rating === "wide" ? "bg-[var(--color-accent)]/10 text-[var(--color-accent)]" :
                              data.moat_rating === "narrow" ? "bg-[var(--color-warning)]/10 text-[var(--color-warning)]" :
                              "bg-[var(--color-danger)]/10 text-[var(--color-danger)]"
                            )}>
                              {data.moat_rating} moat
                            </span>
                          )}
                        </div>
                        <p className="text-sm leading-relaxed text-[var(--color-foreground)]">{data.competitive_moat}</p>
                      </CardContent>
                    </Card>
                  </Section>
                  <Separator className="my-8" />
                </>
              )}

              {/* Revenue Segments */}
              {data.revenue_segments && data.revenue_segments.length > 0 && (
                <>
                  <Section id="revenue" title="Revenue segmentation">
                    <div className="space-y-3">
                      {data.revenue_segments.map((seg, i) => {
                        const trendColor = seg.trend === "growing" ? "var(--color-accent)" : seg.trend === "declining" ? "var(--color-danger)" : "var(--color-muted)";
                        const pct = seg.percentage;
                        return (
                          <div key={i}>
                            <div className="mb-1 flex items-center justify-between text-sm">
                              <div className="flex items-center gap-2">
                                <span className="font-medium text-[var(--color-foreground)]">{seg.name}</span>
                                {seg.trend && seg.trend !== "unknown" && (
                                  <span className="text-[10px] uppercase" style={{ color: trendColor }}>{seg.trend}</span>
                                )}
                              </div>
                              <div className="flex items-center gap-3">
                                <span className="font-mono text-xs tabular-nums text-[var(--color-muted-strong)]">{seg.value}</span>
                                <span className="font-mono text-xs tabular-nums text-[var(--color-foreground)] font-medium w-12 text-right">{pct != null ? `${pct.toFixed(1)}%` : "—"}</span>
                              </div>
                            </div>
                            <div className="h-2.5 w-full rounded-full bg-[var(--color-surface)]">
                              <div
                                className="h-full rounded-full transition-all"
                                style={{
                                  width: `${Math.min(pct ?? 0, 100)}%`,
                                  backgroundColor: "var(--color-accent)",
                                  opacity: 0.4 + ((pct ?? 0) / 100) * 0.6,
                                }}
                              />
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  </Section>
                  <Separator className="my-8" />
                </>
              )}

              {/* Valuation Verdict */}
              {data.valuation_verdict && (
                <>
                  <Section id="valuation" title="Valuation verdict">
                    <Card>
                      <CardContent className="p-5">
                        <div className="mb-3 flex items-center gap-3">
                          <Target className="h-5 w-5 text-[var(--color-accent)]" />
                          {data.valuation_rating && data.valuation_rating !== "unknown" && (
                            <span className={cn(
                              "rounded-full px-2.5 py-0.5 text-xs font-semibold uppercase",
                              data.valuation_rating === "undervalued" ? "bg-[var(--color-accent)]/10 text-[var(--color-accent)]" :
                              data.valuation_rating === "fairly_valued" ? "bg-[var(--color-warning)]/10 text-[var(--color-warning)]" :
                              "bg-[var(--color-danger)]/10 text-[var(--color-danger)]"
                            )}>
                              {data.valuation_rating.replace("_", " ")}
                            </span>
                          )}
                        </div>
                        <p className="text-sm leading-relaxed text-[var(--color-foreground)]">{data.valuation_verdict}</p>
                      </CardContent>
                    </Card>
                  </Section>
                  <Separator className="my-8" />
                </>
              )}

              {/* Catalysts */}
              {data.catalysts && data.catalysts.length > 0 && (
                <>
                  <Section id="catalysts" title="Catalysts & upcoming events">
                    <div className="space-y-3">
                      {data.catalysts.map((c, i) => {
                        const cat = c as { event: string; expected_timing: string; impact: string; rationale: string };
                        const impactColor = cat.impact === "positive" ? "var(--color-accent)" : cat.impact === "negative" ? "var(--color-danger)" : "var(--color-warning)";
                        return (
                          <div key={i} className="flex gap-3 rounded-[var(--radius-md)] border border-[var(--color-border)] bg-[var(--color-surface)] p-4">
                            <div className="mt-0.5">
                              <Zap className="h-4 w-4" style={{ color: impactColor }} />
                            </div>
                            <div className="flex-1">
                              <div className="flex items-center justify-between gap-2">
                                <span className="text-sm font-medium text-[var(--color-foreground)]">{cat.event}</span>
                                <span className="shrink-0 rounded-full border px-2 py-0.5 text-[10px] uppercase" style={{ color: impactColor, borderColor: `color-mix(in oklab, ${impactColor} 40%, transparent)` }}>
                                  {cat.expected_timing}
                                </span>
                              </div>
                              <p className="mt-1 text-xs text-[var(--color-muted)]">{cat.rationale}</p>
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  </Section>
                  <Separator className="my-8" />
                </>
              )}

              {/* Management */}
              {data.management_assessment && (
                <>
                  <Section id="management" title="Management assessment">
                    <Card>
                      <CardContent className="p-5">
                        <div className="mb-3">
                          <Users className="h-5 w-5 text-[var(--color-accent)]" />
                        </div>
                        <p className="text-sm leading-relaxed text-[var(--color-foreground)]">{data.management_assessment}</p>
                      </CardContent>
                    </Card>
                  </Section>
                  <Separator className="my-8" />
                </>
              )}

              {/* Key metrics */}
              {data.key_metrics && data.key_metrics.length > 0 && (
                <>
                  <Section id="metrics" title="Key metrics">
                    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 md:grid-cols-3">
                      {data.key_metrics.map((m, i) => (
                        <MetricTile key={i} metric={m} />
                      ))}
                    </div>
                  </Section>
                  <Separator className="my-8" />
                </>
              )}

              {/* Market Context: News + Peers */}
              {((newsData?.articles && newsData.articles.length > 0) || (peersData?.peers && peersData.peers.length > 0)) && (
                <>
                  <Section id="market-context" title="Market context" defaultOpen={false}>
                    <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
                      {/* Recent news */}
                      {newsData?.articles && newsData.articles.length > 0 && (
                        <Card>
                          <CardHeader><CardTitle>Recent news</CardTitle></CardHeader>
                          <CardContent>
                            <div className="space-y-2.5">
                              {newsData.articles.slice(0, 5).map((a, i) => {
                                const sentColor = (a.sentiment_score ?? 0) > 0.1 ? "var(--color-accent)" : (a.sentiment_score ?? 0) < -0.1 ? "var(--color-danger)" : "var(--color-muted)";
                                return (
                                  <a key={i} href={a.url} target="_blank" rel="noopener noreferrer" className="flex items-start gap-2 group">
                                    <span className="mt-1.5 h-2 w-2 shrink-0 rounded-full" style={{ backgroundColor: sentColor }} />
                                    <div className="flex-1 min-w-0">
                                      <p className="text-xs text-[var(--color-foreground)] group-hover:text-[var(--color-accent)] line-clamp-1">{a.title}</p>
                                      <p className="text-[10px] text-[var(--color-muted)]">{a.source} · {a.published_at?.slice(0, 10)}</p>
                                    </div>
                                    <ExternalLink className="h-3 w-3 shrink-0 text-[var(--color-muted)] opacity-0 group-hover:opacity-100" />
                                  </a>
                                );
                              })}
                            </div>
                          </CardContent>
                        </Card>
                      )}

                      {/* Peer snapshot */}
                      {peersData?.peers && peersData.peers.length > 0 && (
                        <Card>
                          <CardHeader><CardTitle>Peer comparison</CardTitle></CardHeader>
                          <CardContent>
                            <table className="w-full text-xs">
                              <thead>
                                <tr className="border-b border-[var(--color-border)] text-[10px] uppercase tracking-wider text-[var(--color-muted)]">
                                  <th className="pb-2 text-left font-medium">Ticker</th>
                                  <th className="pb-2 text-right font-medium">Price</th>
                                  <th className="pb-2 text-right font-medium">P/E</th>
                                  <th className="pb-2 text-right font-medium">Day</th>
                                </tr>
                              </thead>
                              <tbody>
                                {peersData.peers.slice(0, 5).map((p, i) => (
                                  <tr key={i} className={cn("border-b border-[var(--color-border)] last:border-0", p.symbol === ticker && "bg-[var(--color-accent)]/5")}>
                                    <td className="py-1.5 font-mono font-medium text-[var(--color-foreground)]">{p.symbol}</td>
                                    <td className="py-1.5 text-right tabular-nums text-[var(--color-muted-strong)]">${p.price?.toFixed(2) ?? "—"}</td>
                                    <td className="py-1.5 text-right tabular-nums text-[var(--color-muted-strong)]">{p.pe_ratio?.toFixed(1) ?? "—"}</td>
                                    <td className="py-1.5 text-right tabular-nums" style={{ color: (p.day_change_pct ?? 0) >= 0 ? "var(--color-accent)" : "var(--color-danger)" }}>
                                      {p.day_change_pct != null ? `${p.day_change_pct >= 0 ? "+" : ""}${p.day_change_pct.toFixed(2)}%` : "—"}
                                    </td>
                                  </tr>
                                ))}
                              </tbody>
                            </table>
                          </CardContent>
                        </Card>
                      )}
                    </div>
                  </Section>
                  <Separator className="my-8" />
                </>
              )}

              {/* Citations */}
              {data.citations && data.citations.length > 0 && (
                <Section id="sources" title="Sources" defaultOpen={false}>
                  <ol className="space-y-2 text-sm">
                    {(data.citations as ReportCitation[]).map((c, i) => {
                      const idx = c?.source_index ?? i + 1;
                      const docType = c?.doc_type ?? "";
                      const excerpt = c?.excerpt ?? "";
                      return (
                        <li
                          key={i}
                          className="flex gap-3 rounded-[var(--radius-md)] border border-[var(--color-border)] bg-[var(--color-surface)] p-3"
                        >
                          <span className="shrink-0 font-mono text-xs text-[var(--color-muted)]">
                            [{idx}]
                          </span>
                          <div className="flex-1 space-y-1">
                            {docType && (
                              <span className="rounded-full border border-[var(--color-border)] bg-[var(--color-surface-elevated)] px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide text-[var(--color-muted-strong)]">
                                {docType}
                              </span>
                            )}
                            <p className="break-words text-sm leading-relaxed text-[var(--color-foreground)]">
                              {excerpt || "No excerpt available."}
                            </p>
                          </div>
                        </li>
                      );
                    })}
                  </ol>
                </Section>
              )}

              {/* Follow-up questions */}
              <section id="follow-up" className="mt-8 scroll-mt-20 rounded-[var(--radius-lg)] border border-[var(--color-border)] bg-[var(--color-surface)]/40 p-6">
                <h3 className="text-sm font-medium text-[var(--color-foreground)]">Continue your research</h3>
                <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-2">
                  <Link
                    href={`/workspace/${ticker}?tab=chat`}
                    className="flex items-center gap-3 rounded-[var(--radius-md)] border border-[var(--color-border)] bg-[var(--color-background)] p-4 transition-colors hover:border-[var(--color-accent)]"
                  >
                    <MessageSquare className="h-5 w-5 text-[var(--color-accent)]" />
                    <div>
                      <p className="text-sm font-medium text-[var(--color-foreground)]">Ask follow-up questions</p>
                      <p className="text-xs text-[var(--color-muted)]">Chat with AI about {ticker}&apos;s filings</p>
                    </div>
                  </Link>
                  <Link
                    href={`/workspace/${ticker}?tab=overview`}
                    className="flex items-center gap-3 rounded-[var(--radius-md)] border border-[var(--color-border)] bg-[var(--color-background)] p-4 transition-colors hover:border-[var(--color-accent)]"
                  >
                    <TrendingUp className="h-5 w-5 text-[var(--color-accent)]" />
                    <div>
                      <p className="text-sm font-medium text-[var(--color-foreground)]">Live data overview</p>
                      <p className="text-xs text-[var(--color-muted)]">Charts, financials, and live data for {ticker}</p>
                    </div>
                  </Link>
                </div>
                {/* Suggested deeper questions */}
                <div className="mt-4">
                  <p className="mb-2 text-[10px] uppercase tracking-wider text-[var(--color-muted)]">Suggested questions</p>
                  <div className="flex flex-wrap gap-2">
                    {[
                      `Deep dive into ${ticker}'s revenue risks`,
                      `How is ${ticker}'s debt structured?`,
                      `Compare ${ticker} with its top competitor`,
                      `What's ${ticker}'s growth outlook for next year?`,
                    ].map((q) => (
                      <Link
                        key={q}
                        href={`/workspace/${ticker}?tab=chat&q=${encodeURIComponent(q)}`}
                        className="rounded-full border border-[var(--color-border)] px-3 py-1 text-xs text-[var(--color-muted-strong)] transition-colors hover:border-[var(--color-accent)] hover:text-[var(--color-accent)]"
                      >
                        {q}
                      </Link>
                    ))}
                  </div>
                </div>
              </section>
            </>
          )}
        </main>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Helper components
// ---------------------------------------------------------------------------

function MiniSparkline({ prices, positive }: { prices: Array<{ close?: number | null }>; positive: boolean }) {
  const closes = prices.map((p) => p.close ?? 0).filter((v) => v > 0);
  if (closes.length < 2) return null;
  const min = Math.min(...closes);
  const max = Math.max(...closes);
  const range = max - min || 1;
  const w = 120;
  const h = 32;
  const points = closes.map((v, i) => `${(i / (closes.length - 1)) * w},${h - ((v - min) / range) * h}`).join(" ");
  const color = positive ? "var(--color-accent)" : "var(--color-danger)";
  return (
    <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} className="overflow-visible">
      <polyline fill="none" stroke={color} strokeWidth="1.5" points={points} />
    </svg>
  );
}

function SwotQuadrant({ title, items, color }: { title: string; items: string[]; color: string }) {
  if (!items || items.length === 0) return null;
  return (
    <div className="rounded-[var(--radius-md)] border p-4" style={{ borderColor: `color-mix(in oklab, ${color} 30%, transparent)`, backgroundColor: `color-mix(in oklab, ${color} 5%, transparent)` }}>
      <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider" style={{ color }}>{title}</h3>
      <ul className="space-y-1.5">
        {items.map((item, i) => (
          <li key={i} className="flex items-start gap-2 text-sm leading-snug text-[var(--color-foreground)]">
            <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full" style={{ backgroundColor: color }} />
            {item}
          </li>
        ))}
      </ul>
    </div>
  );
}

function MetricTile({ metric }: { metric: Record<string, unknown> }) {
  const name = (metric.name as string) ?? (metric.label as string) ?? (metric.metric as string) ?? Object.keys(metric)[0];
  const value = metric.value ?? metric[Object.keys(metric).find((k) => k !== "name" && k !== "label" && k !== "metric" && k !== "trend" && k !== "context") ?? ""];
  const trend = metric.trend as string | undefined;
  const context = metric.context as string | undefined;
  const trendColor = trend === "up" ? "var(--color-accent)" : trend === "down" ? "var(--color-danger)" : "var(--color-muted)";
  return (
    <div className="rounded-[var(--radius-md)] border border-[var(--color-border)] bg-[var(--color-surface)] p-4">
      <p className="text-[10px] uppercase tracking-wider text-[var(--color-muted)]">{String(name)}</p>
      <div className="mt-1 flex items-baseline gap-2">
        <p className="font-mono text-lg font-semibold tabular-nums text-[var(--color-foreground)]">
          {value == null ? "—" : String(value)}
        </p>
        {trend && trend !== "unknown" && (
          <span className="text-xs" style={{ color: trendColor }}>
            {trend === "up" ? "+" : trend === "down" ? "-" : "~"}
          </span>
        )}
      </div>
      {context && <p className="mt-1 text-[10px] text-[var(--color-muted)] line-clamp-2">{context}</p>}
    </div>
  );
}
