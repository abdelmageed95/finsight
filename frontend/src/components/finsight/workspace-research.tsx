"use client";

import { useEffect, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { FileText, Sparkles } from "lucide-react";
import { api } from "@/lib/api";
import { cn, formatRelativeTime, riskBucket } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { AnalyzeDialog } from "@/components/finsight/analyze-dialog";
import { ReportDetailView } from "@/components/finsight/report-detail-view";
import { StatusBadge } from "@/components/finsight/status-badge";

interface Props {
  ticker: string;
  jobId: string | null;
  onPickJob: (jobId: string) => void;
}

/**
 * Research tab: a per-ticker picker of past reports + the full detail view
 * of the selected one. When `jobId` is null we auto-select the latest
 * completed report (or render an empty state if none exists).
 */
export function WorkspaceResearch({ ticker, jobId, onPickJob }: Props) {
  const { data: history, isLoading } = useQuery({
    queryKey: ["history", ticker],
    queryFn: () => api.history({ ticker, limit: 20 }),
    retry: false,
  });

  // Show completed reports and any still in progress; hide superseded
  // ("overwritten") and "failed" runs — a failed question is not a report.
  const visible = useMemo(
    () =>
      (history ?? []).filter(
        (r) => r.status !== "overwritten" && r.status !== "failed",
      ),
    [history],
  );

  // Auto-pick the latest completed report if no jobId in URL.
  const latestCompleted = visible.find((r) => r.status === "completed");
  useEffect(() => {
    if (!jobId && latestCompleted?.job_id) {
      onPickJob(latestCompleted.job_id);
    }
  }, [jobId, latestCompleted, onPickJob]);

  if (isLoading) {
    return (
      <div className="py-10 text-center text-sm text-[var(--color-muted)]">
        Loading reports…
      </div>
    );
  }

  if (visible.length === 0) {
    return (
      <Card>
        <CardContent className="flex flex-col items-center gap-4 py-16 text-center">
          <div className="flex h-12 w-12 items-center justify-center rounded-2xl border border-[var(--color-border)] bg-[var(--color-surface)]">
            <FileText className="h-5 w-5 text-[var(--color-accent)]" />
          </div>
          <div>
            <h3 className="text-sm font-semibold text-[var(--color-foreground)]">
              No reports yet for {ticker}
            </h3>
            <p className="mt-1 max-w-md text-xs text-[var(--color-muted)]">
              Generating a report runs the full multi-agent pipeline:
              data agent fetches filings + market data, RAG agent retrieves
              and analyzes, report agent finalizes. Takes ~30–60 seconds.
            </p>
          </div>
          <AnalyzeDialog ticker={ticker} onComplete={(j) => onPickJob(j)}>
            <Button variant="primary" size="md">
              <Sparkles className="h-4 w-4" />
              Generate first report
            </Button>
          </AnalyzeDialog>
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="space-y-6">
      {/* Picker — horizontal scroll if there are many */}
      <div className="overflow-x-auto">
        <div className="flex gap-2">
          {visible.map((r) => {
            const active = r.job_id === jobId;
            const bucket = riskBucket(r.risk_score);
            const dotColor =
              r.risk_score == null
                ? "var(--color-muted)"
                : bucket === "low"
                ? "var(--color-accent)"
                : bucket === "high"
                ? "var(--color-danger)"
                : "var(--color-warning)";
            return (
              <button
                key={r.job_id}
                type="button"
                onClick={() => onPickJob(r.job_id)}
                className={cn(
                  "flex shrink-0 items-center gap-2 rounded-[var(--radius-md)] border px-3 py-2 text-left text-xs transition-colors",
                  active
                    ? "border-[var(--color-accent)] bg-[color:color-mix(in_oklab,var(--color-accent)_10%,transparent)]"
                    : "border-[var(--color-border)] bg-[var(--color-surface)] hover:border-[var(--color-accent)]/60",
                )}
              >
                <span
                  className="h-1.5 w-1.5 shrink-0 rounded-full"
                  style={{ background: dotColor }}
                />
                <span className="max-w-[180px] truncate text-[var(--color-foreground)]">
                  {r.question || "Research report"}
                </span>
                <span className="text-[10px] text-[var(--color-muted)]">
                  {formatRelativeTime(r.created_at)}
                </span>
                <StatusBadge status={r.status} />
              </button>
            );
          })}
        </div>
      </div>

      {/* Detail */}
      {jobId ? (
        <ReportDetailView jobId={jobId} />
      ) : (
        <div className="py-10 text-center text-sm text-[var(--color-muted)]">
          Pick a report above to view the full analysis.
        </div>
      )}
    </div>
  );
}
