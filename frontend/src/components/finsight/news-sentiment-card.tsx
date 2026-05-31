"use client";

import { useQuery } from "@tanstack/react-query";
import { ExternalLink } from "lucide-react";
import { api } from "@/lib/api";
import { parseUtc } from "@/lib/utils";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

interface Article {
  title: string;
  url: string;
  source: string;
  published_at: string | null;
  summary: string;
  sentiment_score: number | null;
  sentiment_label: string | null;
}

interface NewsResponse {
  ticker: string;
  articles: Article[];
}

function sentimentColor(score: number | null, label: string | null): string {
  if (score != null) {
    if (score > 0.15) return "var(--color-accent)";
    if (score < -0.15) return "var(--color-danger)";
    return "var(--color-muted)";
  }
  if (!label) return "var(--color-muted)";
  const l = label.toLowerCase();
  if (l.includes("bull") || l.includes("positive")) return "var(--color-accent)";
  if (l.includes("bear") || l.includes("negative")) return "var(--color-danger)";
  return "var(--color-muted)";
}

function formatNewsDate(dateStr: string | null): string {
  if (!dateStr) return "";
  try {
    const d = parseUtc(dateStr);
    return d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
  } catch {
    return "";
  }
}

export function NewsSentimentCard({ ticker }: { ticker: string }) {
  const { data } = useQuery({
    queryKey: ["news", ticker],
    queryFn: () => api.news(ticker) as Promise<NewsResponse>,
    retry: false,
    staleTime: 1000 * 60 * 15,
  });

  if (!data || data.articles.length === 0) return null;

  // Avg sentiment sparkline
  const scores = data.articles
    .map((a) => a.sentiment_score)
    .filter((s): s is number => s != null);
  const avgSentiment = scores.length > 0 ? scores.reduce((a, b) => a + b, 0) / scores.length : null;

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle>News sentiment</CardTitle>
          {avgSentiment != null && (
            <span
              className="rounded-full px-2 py-0.5 text-[10px] font-medium"
              style={{
                color: sentimentColor(avgSentiment, ""),
                backgroundColor: `color-mix(in oklab, ${sentimentColor(avgSentiment, "")} 12%, transparent)`,
              }}
            >
              Avg: {avgSentiment > 0 ? "+" : ""}{avgSentiment.toFixed(2)}
            </span>
          )}
        </div>
      </CardHeader>
      <CardContent>
        <div className="space-y-2">
          {data.articles.slice(0, 8).map((a, i) => (
            <a
              key={i}
              href={a.url}
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-start gap-2 rounded-[var(--radius-md)] border border-[var(--color-border)] bg-[var(--color-background)] p-2.5 transition-colors hover:border-[var(--color-accent)]"
            >
              {/* Sentiment dot */}
              <span
                className="mt-1.5 h-2 w-2 shrink-0 rounded-full"
                style={{ backgroundColor: sentimentColor(a.sentiment_score, a.sentiment_label) }}
              />
              <div className="flex-1 min-w-0">
                <p className="text-xs font-medium leading-snug text-[var(--color-foreground)] line-clamp-2">
                  {a.title}
                </p>
                <div className="mt-0.5 flex items-center gap-2 text-[10px] text-[var(--color-muted)]">
                  <span>{a.source}</span>
                  {a.published_at && (
                    <>
                      <span className="text-[var(--color-border)]">&middot;</span>
                      <span>{formatNewsDate(a.published_at)}</span>
                    </>
                  )}
                </div>
              </div>
              <ExternalLink className="mt-1 h-3 w-3 shrink-0 text-[var(--color-muted)]" />
            </a>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}
