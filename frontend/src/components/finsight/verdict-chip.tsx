"use client";

import { cn } from "@/lib/utils";

export type Verdict = "buy" | "hold" | "avoid" | "insufficient";

export interface VerdictInputs {
  risk_score?: number | null;
  valuation_rating?: string | null;
  confidence?: string | null;
}

/**
 * Derive a one-word investment verdict from the existing report fields.
 * No new LLM output required — we just combine risk_score + valuation_rating.
 *
 *  🟢 BUY   risk ≤ 40 AND valuation ∈ {undervalued, fairly_valued}
 *  🔴 AVOID risk ≥ 70 OR  valuation = overvalued
 *  ⚪ N/A   confidence = low, or both inputs missing
 *  🟡 HOLD  otherwise
 */
export function deriveVerdict({
  risk_score,
  valuation_rating,
  confidence,
}: VerdictInputs): Verdict {
  if (confidence === "low" || (risk_score == null && !valuation_rating)) {
    return "insufficient";
  }
  const score = risk_score ?? 50;
  const v = (valuation_rating ?? "").toLowerCase();

  if (v === "overvalued") return "avoid";
  if (score >= 70) return "avoid";
  if (score <= 40 && (v === "undervalued" || v === "fairly_valued")) return "buy";
  return "hold";
}

const VARIANTS: Record<Verdict, { dot: string; label: string; cls: string; tooltip: string }> = {
  buy: {
    dot: "🟢",
    label: "Buy candidate",
    cls: "border-[color:color-mix(in_oklab,var(--color-accent)_45%,transparent)] bg-[color:color-mix(in_oklab,var(--color-accent)_10%,transparent)] text-[var(--color-accent)]",
    tooltip: "Low risk and fair-or-better valuation. Worth a closer look.",
  },
  hold: {
    dot: "🟡",
    label: "Hold",
    cls: "border-[color:color-mix(in_oklab,var(--color-warning)_45%,transparent)] bg-[color:color-mix(in_oklab,var(--color-warning)_10%,transparent)] text-[var(--color-warning)]",
    tooltip: "Mixed signals — solid in places, watch-list concerns elsewhere.",
  },
  avoid: {
    dot: "🔴",
    label: "Avoid",
    cls: "border-[color:color-mix(in_oklab,var(--color-danger)_45%,transparent)] bg-[color:color-mix(in_oklab,var(--color-danger)_10%,transparent)] text-[var(--color-danger)]",
    tooltip: "Elevated risk or overvalued relative to fundamentals.",
  },
  insufficient: {
    dot: "⚪",
    label: "Inconclusive",
    cls: "border-[var(--color-border)] bg-[var(--color-surface)] text-[var(--color-muted)]",
    tooltip: "Not enough source data for a confident verdict.",
  },
};

export function VerdictChip({
  inputs,
  size = "sm",
  className,
}: {
  inputs: VerdictInputs;
  size?: "sm" | "md";
  className?: string;
}) {
  const verdict = deriveVerdict(inputs);
  const v = VARIANTS[verdict];
  const sizeCls =
    size === "md" ? "px-3 py-1 text-sm" : "px-2.5 py-0.5 text-xs";
  return (
    <span
      title={v.tooltip}
      className={cn(
        "inline-flex shrink-0 items-center gap-1.5 rounded-full border font-medium",
        v.cls,
        sizeCls,
        className,
      )}
    >
      <span aria-hidden>{v.dot}</span>
      {v.label}
    </span>
  );
}

/**
 * Plain-English risk level + score + rationale, in one short line.
 * Example: "MODERATE risk (52/100) — Strong cash flow but rising AI capex."
 */
export function riskLevelLabel(score?: number | null): string {
  if (score == null) return "Unscored";
  if (score <= 25) return "LOW";
  if (score <= 50) return "MODERATE";
  if (score <= 75) return "ELEVATED";
  return "HIGH";
}
