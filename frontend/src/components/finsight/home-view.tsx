"use client";

import Link from "next/link";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ArrowRight, FileText, Search, Sparkles, Star } from "lucide-react";
import { api } from "@/lib/api";
import { cn, formatRelativeTime, riskBucket } from "@/lib/utils";
import { Input } from "@/components/ui/input";
import { TickerSearch } from "@/components/finsight/ticker-search";
import { StatusBadge } from "@/components/finsight/status-badge";
import { StarButton } from "@/components/finsight/star-button";
import { useAuth } from "@/components/finsight/auth-provider";
import type { ReportStatus } from "@/lib/schemas";

const POPULAR: { t: string; n: string }[] = [
  { t: "AAPL", n: "Apple" },
  { t: "NVDA", n: "NVIDIA" },
  { t: "TSLA", n: "Tesla" },
  { t: "MSFT", n: "Microsoft" },
  { t: "GOOGL", n: "Alphabet" },
  { t: "JPM", n: "JPMorgan" },
];

/**
 * Logged-in home page. Replaces the old flat /reports list with:
 *   1. A prominent ticker launcher at the top
 *   2. Starred reports (if any)
 *   3. Recently run reports (the old reports list, lightly grouped)
 *
 * Reports as a top-level concept goes away; you only ever see them inside
 * a ticker workspace, with this page as the cross-ticker activity feed.
 */
export function HomeView() {
  const { user } = useAuth();
  const [filter, setFilter] = useState("");

  const { data, isLoading } = useQuery({
    queryKey: ["history", "all"],
    queryFn: () => api.history({ limit: 100 }),
  });

  const visible = (data ?? []).filter((r) => {
    if (r.status === "overwritten") return false;
    if (!filter) return true;
    return (
      r.ticker.toLowerCase().includes(filter.toLowerCase()) ||
      r.question?.toLowerCase().includes(filter.toLowerCase())
    );
  });

  const starred = visible.filter((r) => r.is_starred);
  const recent = visible;

  return (
    <div className="flex flex-1 flex-col">
      <header className="border-b border-[var(--color-border)] bg-[var(--color-surface)]/30 px-6 py-10">
        <div className="mx-auto w-full max-w-5xl">
          <p className="text-xs uppercase tracking-wider text-[var(--color-muted)]">
            {user ? `Welcome back, ${user.name || user.email.split("@")[0]}` : "Home"}
          </p>
          <h1 className="mt-1 text-2xl font-semibold text-[var(--color-foreground)] sm:text-3xl">
            Pick a company to research
          </h1>
          <p className="mt-2 max-w-2xl text-sm text-[var(--color-muted-strong)]">
            Search any US public company by ticker or name. The workspace shows
            live data, generated reports, and a chat — all in one place.
          </p>
          <div className="mt-6 max-w-2xl">
            <TickerSearch autoFocus={false} />
          </div>
          <div className="mt-4 flex flex-wrap items-center gap-2">
            <span className="text-xs text-[var(--color-muted)]">Popular:</span>
            {POPULAR.map((s) => (
              <Link
                key={s.t}
                href={`/workspace/${s.t}`}
                className="inline-flex items-center gap-1.5 rounded-full border border-[var(--color-border)] bg-[var(--color-surface)] px-3 py-1 text-xs text-[var(--color-muted-strong)] transition-colors hover:border-[var(--color-accent)] hover:text-[var(--color-accent)]"
              >
                <span className="font-mono font-semibold text-[var(--color-foreground)]">
                  {s.t}
                </span>
                <span className="text-[var(--color-muted)]">·</span>
                <span>{s.n}</span>
              </Link>
            ))}
          </div>
        </div>
      </header>

      <main className="mx-auto w-full max-w-5xl flex-1 px-6 py-10">
        {/* Filter row */}
        <div className="mb-6 flex flex-wrap items-center justify-between gap-4">
          <h2 className="text-sm font-semibold uppercase tracking-wider text-[var(--color-muted)]">
            Your activity
          </h2>
          <div className="relative w-72">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[var(--color-muted)]" />
            <Input
              placeholder="Filter by ticker or question…"
              className="pl-9"
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
            />
          </div>
        </div>

        {isLoading ? (
          <div className="py-16 text-center text-sm text-[var(--color-muted)]">
            Loading…
          </div>
        ) : visible.length === 0 ? (
          <EmptyState />
        ) : (
          <div className="space-y-8">
            {starred.length > 0 && (
              <Section
                title="Starred"
                icon={<Star className="h-3.5 w-3.5 text-[var(--color-warning)]" />}
                reports={starred}
              />
            )}
            <Section
              title="Recently run"
              icon={<FileText className="h-3.5 w-3.5 text-[var(--color-accent)]" />}
              reports={recent}
            />
          </div>
        )}
      </main>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Section + row
// ---------------------------------------------------------------------------

type ReportRow = {
  job_id: string;
  ticker: string;
  question?: string | null;
  risk_score?: number | null;
  status: ReportStatus;
  created_at?: string | null;
  is_starred?: boolean;
};

function Section({
  title,
  icon,
  reports,
}: {
  title: string;
  icon: React.ReactNode;
  reports: ReportRow[];
}) {
  return (
    <section>
      <h3 className="mb-3 flex items-center gap-2 text-xs uppercase tracking-wider text-[var(--color-muted)]">
        {icon}
        {title}
        <span className="text-[var(--color-muted)]">({reports.length})</span>
      </h3>
      <div className="overflow-hidden rounded-[var(--radius-lg)] border border-[var(--color-border)] bg-[var(--color-surface)]">
        <table className="w-full text-sm">
          <thead className="border-b border-[var(--color-border)] bg-[var(--color-surface-elevated)] text-xs uppercase tracking-wider text-[var(--color-muted)]">
            <tr>
              <th className="w-10 px-5 py-3 text-left"></th>
              <th className="px-5 py-3 text-left">Ticker</th>
              <th className="px-5 py-3 text-left">Question</th>
              <th className="px-5 py-3 text-left">Risk</th>
              <th className="px-5 py-3 text-left">Status</th>
              <th className="px-5 py-3 text-right">Generated</th>
            </tr>
          </thead>
          <tbody>
            {reports.map((r) => {
              const bucket = riskBucket(r.risk_score);
              const color =
                r.risk_score == null
                  ? "var(--color-muted)"
                  : bucket === "low"
                  ? "var(--color-accent)"
                  : bucket === "high"
                  ? "var(--color-danger)"
                  : "var(--color-warning)";
              return (
                <tr
                  key={r.job_id}
                  className="group cursor-pointer border-b border-[var(--color-border)] transition-colors last:border-0 hover:bg-[var(--color-surface-elevated)]"
                >
                  <td className="px-3 py-4">
                    <StarButton jobId={r.job_id} starred={!!r.is_starred} />
                  </td>
                  <td className="px-5 py-4">
                    <Link
                      href={`/workspace/${r.ticker}?tab=research&job=${r.job_id}`}
                      className="font-mono font-medium text-[var(--color-foreground)] group-hover:text-[var(--color-accent)]"
                    >
                      {r.ticker}
                    </Link>
                  </td>
                  <td className="max-w-md px-5 py-4">
                    <Link
                      href={`/workspace/${r.ticker}?tab=research&job=${r.job_id}`}
                      className="line-clamp-1 text-[var(--color-muted-strong)] group-hover:text-[var(--color-foreground)]"
                    >
                      {r.question ?? "—"}
                    </Link>
                  </td>
                  <td className="px-5 py-4">
                    {r.risk_score != null ? (
                      <span
                        className={cn(
                          "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 font-mono text-xs tabular-nums",
                        )}
                        style={{
                          color,
                          borderColor: `color-mix(in oklab, ${color} 40%, transparent)`,
                          background: `color-mix(in oklab, ${color} 10%, transparent)`,
                        }}
                      >
                        {r.risk_score}
                      </span>
                    ) : (
                      <span className="text-[var(--color-muted)]">—</span>
                    )}
                  </td>
                  <td className="px-5 py-4">
                    <StatusBadge status={r.status} />
                  </td>
                  <td className="px-5 py-4 text-right text-xs text-[var(--color-muted)]">
                    {formatRelativeTime(r.created_at)}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function EmptyState() {
  return (
    <div className="rounded-[var(--radius-lg)] border border-dashed border-[var(--color-border)] bg-[var(--color-surface)]/40 px-6 py-16 text-center">
      <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-full border border-[var(--color-border)] bg-[var(--color-surface)]">
        <Sparkles className="h-5 w-5 text-[var(--color-accent)]" />
      </div>
      <p className="mt-4 text-sm font-medium text-[var(--color-foreground)]">
        No reports yet
      </p>
      <p className="mt-1 text-xs text-[var(--color-muted)]">
        Pick a popular company above, or search any ticker to get started.
      </p>
      <div className="mt-5 flex flex-wrap justify-center gap-2">
        {POPULAR.map((s) => (
          <Link
            key={s.t}
            href={`/workspace/${s.t}`}
            className="inline-flex items-center gap-2 rounded-full border border-[var(--color-border)] bg-[var(--color-surface)] px-3 py-1 text-xs text-[var(--color-muted-strong)] transition-colors hover:border-[var(--color-accent)] hover:text-[var(--color-accent)]"
          >
            <span className="font-mono font-semibold text-[var(--color-foreground)]">
              {s.t}
            </span>
            <ArrowRight className="h-3 w-3 text-[var(--color-muted)]" />
          </Link>
        ))}
      </div>
    </div>
  );
}
