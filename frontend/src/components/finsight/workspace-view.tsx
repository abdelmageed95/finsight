"use client";

import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import {
  BarChart3,
  FileText,
  Loader2,
  MessageSquare,
  RefreshCw,
  Sparkles,
} from "lucide-react";
import { api } from "@/lib/api";
import { cn, formatCurrency, formatPercent, formatRelativeTime } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { AnalyzeDialog } from "@/components/finsight/analyze-dialog";
import { CompareButton } from "@/components/finsight/compare-button";
import { WorkspaceOverview } from "@/components/finsight/workspace-overview";
import { WorkspaceResearch } from "@/components/finsight/workspace-research";
import { WorkspaceChat } from "@/components/finsight/workspace-chat";

type Tab = "overview" | "research" | "chat";

const TABS: { key: Tab; label: string; icon: typeof BarChart3; hint: string }[] = [
  { key: "overview", label: "Overview", icon: BarChart3, hint: "Live market data" },
  { key: "research", label: "Research", icon: FileText, hint: "AI-generated reports" },
  { key: "chat", label: "Chat", icon: MessageSquare, hint: "Ask questions" },
];

function isTab(v: string | null): v is Tab {
  return v === "overview" || v === "research" || v === "chat";
}

export function WorkspaceView({ ticker }: { ticker: string }) {
  // Persist last-viewed ticker so the sidebar Workspace link remembers it.
  if (typeof window !== "undefined") {
    window.localStorage.setItem("finsight.lastTicker", ticker);
  }

  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const rawTab = searchParams.get("tab");
  const tab: Tab = isTab(rawTab) ? rawTab : "overview";
  const jobIdParam = searchParams.get("job");

  const qc = useQueryClient();
  const [refreshing, setRefreshing] = useState(false);

  const { data, isLoading, error } = useQuery({
    queryKey: ["ticker", ticker],
    queryFn: () => api.ticker(ticker),
    retry: false,
  });

  function setTab(next: Tab, extra?: Record<string, string>) {
    const params = new URLSearchParams(searchParams.toString());
    params.set("tab", next);
    if (extra) {
      for (const [k, v] of Object.entries(extra)) params.set(k, v);
    } else {
      // Clear job-specific params when switching tabs unless caller wants them.
      params.delete("job");
    }
    router.replace(`${pathname}?${params.toString()}`);
  }

  async function handleRefresh() {
    setRefreshing(true);
    try {
      await api.refreshTicker(ticker);
      qc.invalidateQueries({ queryKey: ["ticker", ticker] });
      qc.invalidateQueries({ queryKey: ["history", ticker] });
    } catch {
      // Silently fail — UI keeps stale data.
    } finally {
      setRefreshing(false);
    }
  }

  if (isLoading) {
    return (
      <div className="flex flex-1 items-center justify-center p-10">
        <div className="text-sm text-[var(--color-muted)]">Loading {ticker}…</div>
      </div>
    );
  }

  if (error || !data) {
    return <WorkspaceNotFound ticker={ticker} />;
  }

  const positive = (data.day_change ?? 0) >= 0;

  return (
    <div className="flex flex-1 flex-col">
      {/* Sticky header — shared across all tabs */}
      <header className="sticky top-0 z-20 border-b border-[var(--color-border)] bg-[var(--color-background)]/85 backdrop-blur-xl">
        <div className="mx-auto flex w-full max-w-7xl flex-wrap items-center justify-between gap-4 px-6 py-4">
          <div className="flex items-baseline gap-4">
            <h1 className="font-mono text-2xl font-semibold tracking-wide text-[var(--color-foreground)]">
              {data.symbol}
            </h1>
            <span className="text-sm text-[var(--color-muted-strong)]">
              {data.company_name ?? "—"}
            </span>
          </div>
          <div className="flex items-center gap-3">
            <div className="flex items-baseline gap-2">
              <span className="font-mono text-2xl font-semibold tabular-nums text-[var(--color-foreground)]">
                {formatCurrency(data.latest_price, 2)}
              </span>
              <span
                className={cn(
                  "inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium",
                  positive
                    ? "border-[color:color-mix(in_oklab,var(--color-accent)_40%,transparent)] bg-[color:color-mix(in_oklab,var(--color-accent)_12%,transparent)] text-[var(--color-accent)]"
                    : "border-[color:color-mix(in_oklab,var(--color-danger)_40%,transparent)] bg-[color:color-mix(in_oklab,var(--color-danger)_12%,transparent)] text-[var(--color-danger)]",
                )}
              >
                {data.day_change != null
                  ? `${positive ? "+" : ""}${data.day_change.toFixed(2)} (${formatPercent(data.day_change_pct)})`
                  : "—"}
              </span>
            </div>
            {tab === "overview" && (
              <Button
                variant="ghost"
                size="md"
                onClick={handleRefresh}
                disabled={refreshing}
                title="Refresh market data and news"
              >
                {refreshing ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <RefreshCw className="h-4 w-4" />
                )}
                {refreshing ? "Refreshing…" : "Refresh"}
              </Button>
            )}
            <CompareButton ticker={data.symbol} />
            <AnalyzeDialog
              ticker={data.symbol}
              onComplete={(jobId) => setTab("research", { job: jobId })}
            >
              <Button variant="primary" size="md">
                <Sparkles className="h-4 w-4" />
                Generate report
              </Button>
            </AnalyzeDialog>
          </div>
        </div>
        <div className="mx-auto flex w-full max-w-7xl items-center justify-between px-6 pb-2 text-[11px] uppercase tracking-wider text-[var(--color-muted)]">
          <div className="flex items-center gap-3">
            <span>{data.sector ?? "—"}</span>
            <span className="text-[var(--color-border-strong)]">·</span>
            <span>{data.industry ?? "—"}</span>
          </div>
          <span>Updated {formatRelativeTime(data.updated_at)}</span>
        </div>

        {/* Tab nav */}
        <nav
          role="tablist"
          aria-label="Workspace sections"
          className="mx-auto flex w-full max-w-7xl gap-1 px-4"
        >
          {TABS.map((t) => {
            const Icon = t.icon;
            const active = tab === t.key;
            return (
              <button
                key={t.key}
                type="button"
                role="tab"
                aria-selected={active}
                onClick={() => setTab(t.key)}
                title={t.hint}
                className={cn(
                  "relative flex items-center gap-2 px-3 py-2.5 text-sm transition-colors",
                  active
                    ? "text-[var(--color-foreground)]"
                    : "text-[var(--color-muted-strong)] hover:text-[var(--color-foreground)]",
                )}
              >
                <Icon className="h-4 w-4" />
                {t.label}
                {active && (
                  <span className="absolute inset-x-2 -bottom-px h-0.5 rounded-full bg-[var(--color-accent)]" />
                )}
              </button>
            );
          })}
        </nav>
      </header>

      <main className="mx-auto w-full max-w-7xl flex-1 px-6 py-8">
        {tab === "overview" && (
          <WorkspaceOverview
            ticker={data.symbol}
            data={data}
            onAskInChat={(question) =>
              setTab("chat", { q: question })
            }
            onOpenResearch={(jobId) =>
              setTab("research", jobId ? { job: jobId } : {})
            }
          />
        )}
        {tab === "research" && (
          <WorkspaceResearch
            ticker={data.symbol}
            jobId={jobIdParam}
            onPickJob={(jobId) =>
              router.replace(`${pathname}?tab=research&job=${jobId}`)
            }
          />
        )}
        {tab === "chat" && <WorkspaceChat ticker={data.symbol} />}
      </main>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Not-found state (unknown ticker)
// ---------------------------------------------------------------------------

function WorkspaceNotFound({ ticker }: { ticker: string }) {
  const { data: suggestions } = useQuery({
    queryKey: ["suggest", ticker],
    queryFn: () => api.suggestTickers(ticker, 4),
    retry: false,
    staleTime: 60 * 60 * 1000,
  });

  return (
    <div className="mx-auto flex max-w-2xl flex-1 flex-col items-center justify-center gap-6 p-10 text-center">
      <div className="flex h-16 w-16 items-center justify-center rounded-2xl border border-[var(--color-border)] bg-[var(--color-surface)]">
        <Sparkles className="h-7 w-7 text-[var(--color-accent)]" />
      </div>
      <div>
        <h2 className="text-2xl font-semibold text-[var(--color-foreground)]">
          {ticker} hasn&apos;t been analyzed yet
        </h2>
        <p className="mt-2 max-w-md text-sm text-[var(--color-muted-strong)]">
          Click below to run the full pipeline — the data agent will fetch
          market prices and SEC filings, then the RAG agent will produce a
          cited research report.
        </p>
      </div>
      <AnalyzeDialog ticker={ticker}>
        <Button variant="primary" size="lg">
          <Sparkles className="h-4 w-4" />
          Analyze {ticker}
        </Button>
      </AnalyzeDialog>
      {suggestions && suggestions.length > 0 && (
        <div className="text-sm text-[var(--color-muted)]">
          Did you mean:{" "}
          {suggestions.map((s, i) => (
            <span key={s.ticker}>
              <a
                href={`/workspace/${s.ticker}`}
                className="font-mono text-[var(--color-accent)] hover:underline"
              >
                {s.ticker}
              </a>
              {i < suggestions.length - 1 ? ", " : ""}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
