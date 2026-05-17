"use client";

import { useState } from "react";
import { MessagesSquare, Sparkles } from "lucide-react";
import { AnalyzeDialog } from "./analyze-dialog";

const SUGGESTED: { label: string; question: string }[] = [
  { label: "What are the main risks?", question: "What are the main risks?" },
  { label: "Is this a good long-term investment?", question: "Is this a good long-term investment?" },
  { label: "Summarize the latest 10-K", question: "Summarize the latest 10-K" },
  { label: "How is revenue trending?", question: "How is revenue trending?" },
  { label: "What's the competitive moat?", question: "What's the competitive moat?" },
  { label: "Is the valuation reasonable?", question: "Is the valuation reasonable?" },
];

/**
 * Single-tap question chips. By default each chip opens the AnalyzeDialog
 * (full report generation); pass `onSelect` to instead route the question
 * into the Chat tab (lighter, multi-turn).
 */
export function SuggestedQuestions({
  ticker,
  onSelect,
}: {
  ticker: string;
  onSelect?: (question: string) => void;
}) {
  const [pending, setPending] = useState<string | null>(null);

  if (onSelect) {
    return (
      <div className="rounded-[var(--radius-lg)] border border-[var(--color-border)] bg-[var(--color-surface)]/40 p-4">
        <div className="mb-3 flex items-center gap-2 text-xs uppercase tracking-wider text-[var(--color-muted)]">
          <MessagesSquare className="h-3.5 w-3.5" />
          Common questions about {ticker}
        </div>
        <div className="flex flex-wrap gap-2">
          {SUGGESTED.map((s) => (
            <button
              key={s.question}
              type="button"
              onClick={() => onSelect(s.question)}
              className="inline-flex items-center gap-1.5 rounded-full border border-[var(--color-border)] bg-[var(--color-background)] px-3 py-1.5 text-xs text-[var(--color-foreground)] transition-colors hover:border-[var(--color-accent)] hover:text-[var(--color-accent)]"
            >
              <Sparkles className="h-3 w-3" />
              {s.label}
            </button>
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="rounded-[var(--radius-lg)] border border-[var(--color-border)] bg-[var(--color-surface)]/40 p-4">
      <div className="mb-3 flex items-center gap-2 text-xs uppercase tracking-wider text-[var(--color-muted)]">
        <MessagesSquare className="h-3.5 w-3.5" />
        Common questions about {ticker}
      </div>
      <div className="flex flex-wrap gap-2">
        {SUGGESTED.map((s) => (
          <AnalyzeDialog key={s.question} ticker={ticker} defaultQuestion={s.question}>
            <button
              type="button"
              onClick={() => setPending(s.question)}
              className="inline-flex items-center gap-1.5 rounded-full border border-[var(--color-border)] bg-[var(--color-background)] px-3 py-1.5 text-xs text-[var(--color-foreground)] transition-colors hover:border-[var(--color-accent)] hover:text-[var(--color-accent)]"
            >
              <Sparkles className="h-3 w-3" />
              {s.label}
            </button>
          </AnalyzeDialog>
        ))}
      </div>
      {pending && <span className="sr-only">Analyzing: {pending}</span>}
    </div>
  );
}
