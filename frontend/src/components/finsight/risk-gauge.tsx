import { cn, riskBucket } from "@/lib/utils";

interface RiskGaugeProps {
  score: number | null | undefined;
  size?: number;
  label?: string;
  className?: string;
}

/**
 * Semicircular 0–100 risk gauge.
 * Low  (0–30)  → emerald
 * Mid  (31–70) → amber
 * High (71–100)→ rose
 */
export function RiskGauge({ score, size = 180, label, className }: RiskGaugeProps) {
  const isUnscored = score == null;
  const clamped = Math.max(0, Math.min(100, score ?? 0));
  const bucket = riskBucket(score);
  const color = isUnscored
    ? "var(--color-muted)"
    : bucket === "low"
    ? "var(--color-accent)"
    : bucket === "high"
    ? "var(--color-danger)"
    : "var(--color-warning)";
  const bucketLabel = isUnscored
    ? "Insufficient data"
    : bucket === "low"
    ? "Low risk"
    : bucket === "high"
    ? "High risk"
    : "Moderate risk";

  // Semicircle arc geometry
  const strokeWidth = 14;
  const radius = (size - strokeWidth) / 2;
  const cy = size / 2;
  // half circumference (π r) is the full arc length for a semicircle
  const arcLength = Math.PI * radius;
  const progress = (clamped / 100) * arcLength;

  return (
    <div className={cn("flex flex-col items-center", className)}>
      <svg
        width={size}
        height={size / 2 + 10}
        viewBox={`0 0 ${size} ${size / 2 + 10}`}
        className="overflow-visible"
      >
        {/* Track */}
        <path
          d={`M ${strokeWidth / 2} ${cy} A ${radius} ${radius} 0 0 1 ${
            size - strokeWidth / 2
          } ${cy}`}
          fill="none"
          stroke="var(--color-border)"
          strokeWidth={strokeWidth}
          strokeLinecap="round"
        />
        {/* Progress */}
        <path
          d={`M ${strokeWidth / 2} ${cy} A ${radius} ${radius} 0 0 1 ${
            size - strokeWidth / 2
          } ${cy}`}
          fill="none"
          stroke={color}
          strokeWidth={strokeWidth}
          strokeLinecap="round"
          strokeDasharray={`${progress} ${arcLength}`}
          style={{
            transition: "stroke-dasharray 800ms cubic-bezier(0.22, 1, 0.36, 1)",
            filter: `drop-shadow(0 0 8px color-mix(in oklab, ${color} 40%, transparent))`,
          }}
        />
      </svg>
      <div className="-mt-8 flex flex-col items-center">
        <span
          className="font-mono text-3xl font-semibold tabular-nums"
          style={{ color }}
        >
          {score == null ? "—" : clamped.toFixed(0)}
        </span>
        <span className="text-[10px] uppercase tracking-widest text-[var(--color-muted)]">
          {label ?? bucketLabel}
        </span>
      </div>
    </div>
  );
}
