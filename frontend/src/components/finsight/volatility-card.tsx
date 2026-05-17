"use client";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { Candle } from "@/components/finsight/candlestick-chart";

interface VolatilityCardProps {
  prices: Candle[];
  window?: number;
}

/**
 * Compute annualised rolling volatility (std of daily log returns).
 */
function computeRollingVol(prices: Candle[], window: number): number[] {
  if (prices.length < window + 1) return [];
  // daily log returns
  const returns: number[] = [];
  for (let i = 1; i < prices.length; i++) {
    if (prices[i].close > 0 && prices[i - 1].close > 0) {
      returns.push(Math.log(prices[i].close / prices[i - 1].close));
    } else {
      returns.push(0);
    }
  }
  const vols: number[] = [];
  for (let i = window - 1; i < returns.length; i++) {
    let sum = 0;
    for (let j = 0; j < window; j++) sum += returns[i - j];
    const mean = sum / window;
    let sqSum = 0;
    for (let j = 0; j < window; j++) sqSum += (returns[i - j] - mean) ** 2;
    const std = Math.sqrt(sqSum / window);
    vols.push(std * Math.sqrt(252) * 100); // annualised %
  }
  return vols;
}

export function VolatilityCard({ prices, window: win = 30 }: VolatilityCardProps) {
  const vols = computeRollingVol(prices, win);
  if (vols.length === 0) return null;

  const currentVol = vols[vols.length - 1];
  const maxVol = Math.max(...vols, 1);
  const minVol = Math.min(...vols, 0);
  const range = maxVol - minVol || 1;

  // Downsample to ~40 points for the sparkline
  const step = Math.max(1, Math.floor(vols.length / 40));
  const sampled = vols.filter((_, i) => i % step === 0 || i === vols.length - 1);

  // Build SVG path
  const w = 200;
  const h = 36;
  const points = sampled.map((v, i) => {
    const x = (i / (sampled.length - 1)) * w;
    const y = h - ((v - minVol) / range) * h;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  });
  const pathD = `M${points.join("L")}`;

  return (
    <Card className="hover:border-[var(--color-border-strong)]">
      <CardHeader>
        <CardTitle>{win}-day volatility</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="flex items-baseline gap-2">
          <span className="font-mono text-2xl font-semibold tabular-nums text-[var(--color-foreground)]">
            {currentVol.toFixed(1)}%
          </span>
          <span className="text-xs text-[var(--color-muted)]">annualised</span>
        </div>
        <svg
          viewBox={`0 0 ${w} ${h}`}
          className="mt-2 w-full"
          style={{ height: 36 }}
          preserveAspectRatio="none"
        >
          <path
            d={pathD}
            fill="none"
            stroke="var(--color-accent)"
            strokeWidth="1.5"
            strokeLinejoin="round"
          />
        </svg>
      </CardContent>
    </Card>
  );
}
