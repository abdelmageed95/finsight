"use client";

import { ExternalLink, FileText } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { LatestFiling } from "@/lib/schemas";

interface FilingTimelineProps {
  filings: LatestFiling[];
}

export function FilingTimeline({ filings }: FilingTimelineProps) {
  if (!filings.length) return null;

  return (
    <Card>
      <CardHeader>
        <CardTitle>SEC filings</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="relative space-y-0">
          {filings.map((f, i) => (
            <div key={f.accession_number ?? i} className="flex items-start gap-3 pb-4 last:pb-0">
              {/* Timeline dot + line */}
              <div className="relative flex flex-col items-center">
                <div
                  className={`h-3 w-3 shrink-0 rounded-full border-2 ${
                    f.filing_type === "10-K"
                      ? "border-[var(--color-accent)] bg-[var(--color-accent)]"
                      : "border-[var(--color-muted)] bg-[var(--color-surface)]"
                  }`}
                />
                {i < filings.length - 1 && (
                  <div className="absolute top-3 h-full w-px bg-[var(--color-border)]" />
                )}
              </div>

              {/* Content */}
              <div className="flex flex-1 items-baseline justify-between gap-2 -mt-0.5">
                <div className="flex items-center gap-2">
                  <span
                    className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-medium uppercase tracking-wider ${
                      f.filing_type === "10-K"
                        ? "bg-[color:color-mix(in_oklab,var(--color-accent)_12%,transparent)] text-[var(--color-accent)]"
                        : "bg-[var(--color-surface)] text-[var(--color-muted-strong)]"
                    }`}
                  >
                    <FileText className="h-2.5 w-2.5" />
                    {f.filing_type}
                  </span>
                  {f.source_url && (
                    <a
                      href={f.source_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-[var(--color-muted)] transition-colors hover:text-[var(--color-accent)]"
                    >
                      <ExternalLink className="h-3 w-3" />
                    </a>
                  )}
                </div>
                <span className="shrink-0 text-xs text-[var(--color-muted)]">
                  {f.filed_date ?? "—"}
                </span>
              </div>
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}
