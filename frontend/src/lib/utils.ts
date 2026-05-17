import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function formatCurrency(value: number | null | undefined, digits = 2) {
  if (value == null || Number.isNaN(value)) return "—";
  const abs = Math.abs(value);
  if (abs >= 1_000_000_000_000) return `$${(value / 1_000_000_000_000).toFixed(digits)}T`;
  if (abs >= 1_000_000_000) return `$${(value / 1_000_000_000).toFixed(digits)}B`;
  if (abs >= 1_000_000) return `$${(value / 1_000_000).toFixed(digits)}M`;
  if (abs >= 1_000) return `$${(value / 1_000).toFixed(digits)}K`;
  return `$${value.toFixed(digits)}`;
}

export function formatNumber(value: number | null | undefined, digits = 2) {
  if (value == null || Number.isNaN(value)) return "—";
  return value.toLocaleString(undefined, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

export function formatPercent(value: number | null | undefined, digits = 2) {
  if (value == null || Number.isNaN(value)) return "—";
  const sign = value >= 0 ? "+" : "";
  return `${sign}${value.toFixed(digits)}%`;
}

/**
 * Parse a backend timestamp into a Date.
 *
 * The API emits naive UTC timestamps (`datetime.utcnow()`) with no timezone
 * suffix, e.g. "2026-05-16T12:00:00". JavaScript parses a timezone-less ISO
 * string as *local* time, which skews every relative time by the viewer's
 * UTC offset. Append "Z" so such strings are correctly read as UTC.
 */
export function parseUtc(date: string | Date): Date {
  if (date instanceof Date) return date;
  const hasTz = /([zZ]|[+-]\d{2}:?\d{2})$/.test(date);
  const isDateTime = date.includes("T");
  return new Date(isDateTime && !hasTz ? `${date}Z` : date);
}

export function formatRelativeTime(date: string | Date | null | undefined) {
  if (!date) return "—";
  const d = parseUtc(date);
  const diffMs = Date.now() - d.getTime();
  const diffSec = Math.floor(diffMs / 1000);
  if (diffSec < 60) return "just now";
  if (diffSec < 3600) return `${Math.floor(diffSec / 60)}m ago`;
  if (diffSec < 86400) return `${Math.floor(diffSec / 3600)}h ago`;
  if (diffSec < 2592000) return `${Math.floor(diffSec / 86400)}d ago`;
  return d.toLocaleDateString();
}

export function riskBucket(score: number | null | undefined): "low" | "medium" | "high" {
  if (score == null) return "medium";
  if (score <= 30) return "low";
  if (score <= 70) return "medium";
  return "high";
}

export function riskColor(score: number | null | undefined): string {
  const b = riskBucket(score);
  if (b === "low") return "var(--color-accent)";
  if (b === "high") return "var(--color-danger)";
  return "var(--color-warning)";
}
