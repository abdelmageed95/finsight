"use client";

import { useEffect, useRef, useState } from "react";
import {
  createChart,
  CandlestickSeries,
  HistogramSeries,
  LineSeries,
  type IChartApi,
  type ISeriesApi,
  type Time,
  ColorType,
  CrosshairMode,
} from "lightweight-charts";
import { cn } from "@/lib/utils";

export interface Candle {
  time: Time; // "YYYY-MM-DD" or epoch seconds
  open: number;
  high: number;
  low: number;
  close: number;
  volume?: number;
}

interface CandlestickChartProps {
  data: Candle[];
  height?: number;
}

// ---------------------------------------------------------------------------
// Indicator math (client-side, from price data)
// ---------------------------------------------------------------------------

function computeSMA(data: Candle[], period: number): { time: Time; value: number }[] {
  const result: { time: Time; value: number }[] = [];
  for (let i = period - 1; i < data.length; i++) {
    let sum = 0;
    for (let j = 0; j < period; j++) sum += data[i - j].close;
    result.push({ time: data[i].time, value: sum / period });
  }
  return result;
}

function computeBollinger(
  data: Candle[],
  period: number,
  mult: number
): { upper: { time: Time; value: number }[]; lower: { time: Time; value: number }[] } {
  const upper: { time: Time; value: number }[] = [];
  const lower: { time: Time; value: number }[] = [];
  for (let i = period - 1; i < data.length; i++) {
    let sum = 0;
    for (let j = 0; j < period; j++) sum += data[i - j].close;
    const mean = sum / period;
    let sqSum = 0;
    for (let j = 0; j < period; j++) sqSum += (data[i - j].close - mean) ** 2;
    const std = Math.sqrt(sqSum / period);
    upper.push({ time: data[i].time, value: mean + mult * std });
    lower.push({ time: data[i].time, value: mean - mult * std });
  }
  return { upper, lower };
}

type Overlay = "sma20" | "sma50" | "bollinger";

export function CandlestickChart({ data, height = 420 }: CandlestickChartProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const overlaySeriesRef = useRef<ISeriesApi<"Line">[]>([]);
  const [activeOverlays, setActiveOverlays] = useState<Set<Overlay>>(new Set());

  function toggleOverlay(o: Overlay) {
    setActiveOverlays((prev) => {
      const next = new Set(prev);
      if (next.has(o)) next.delete(o);
      else next.add(o);
      return next;
    });
  }

  useEffect(() => {
    if (!containerRef.current) return;

    const chart = createChart(containerRef.current, {
      layout: {
        background: { type: ColorType.Solid, color: "transparent" },
        textColor: "#8a8a93",
        fontFamily:
          'var(--font-geist-mono), ui-monospace, SFMono-Regular, Menlo, monospace',
        fontSize: 11,
      },
      grid: {
        vertLines: { color: "rgba(38, 38, 42, 0.5)" },
        horzLines: { color: "rgba(38, 38, 42, 0.5)" },
      },
      crosshair: {
        mode: CrosshairMode.Normal,
        vertLine: { color: "#35353b", width: 1, style: 3, labelBackgroundColor: "#1a1a1f" },
        horzLine: { color: "#35353b", width: 1, style: 3, labelBackgroundColor: "#1a1a1f" },
      },
      rightPriceScale: {
        borderColor: "#26262a",
      },
      timeScale: {
        borderColor: "#26262a",
        timeVisible: false,
        secondsVisible: false,
      },
      height,
      autoSize: true,
    });
    chartRef.current = chart;

    // Candles
    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: "#10b981",
      downColor: "#f43f5e",
      borderUpColor: "#10b981",
      borderDownColor: "#f43f5e",
      wickUpColor: "#10b981",
      wickDownColor: "#f43f5e",
    });

    // Volume
    const volumeSeries = chart.addSeries(HistogramSeries, {
      priceFormat: { type: "volume" },
      priceScaleId: "",
    });
    volumeSeries.priceScale().applyOptions({
      scaleMargins: { top: 0.8, bottom: 0 },
    });

    candleSeries.setData(
      data.map((d) => ({
        time: d.time,
        open: d.open,
        high: d.high,
        low: d.low,
        close: d.close,
      }))
    );
    volumeSeries.setData(
      data
        .filter((d) => d.volume != null)
        .map((d) => ({
          time: d.time,
          value: d.volume!,
          color:
            d.close >= d.open
              ? "rgba(16, 185, 129, 0.45)"
              : "rgba(244, 63, 94, 0.45)",
        }))
    );

    // Overlays
    const overlaySeries: ISeriesApi<"Line">[] = [];

    if (activeOverlays.has("sma20")) {
      const sma20 = chart.addSeries(LineSeries, {
        color: "#f59e0b",
        lineWidth: 1,
        priceLineVisible: false,
        lastValueVisible: false,
      });
      sma20.setData(computeSMA(data, 20));
      overlaySeries.push(sma20);
    }

    if (activeOverlays.has("sma50")) {
      const sma50 = chart.addSeries(LineSeries, {
        color: "#3b82f6",
        lineWidth: 1,
        priceLineVisible: false,
        lastValueVisible: false,
      });
      sma50.setData(computeSMA(data, 50));
      overlaySeries.push(sma50);
    }

    if (activeOverlays.has("bollinger")) {
      const bb = computeBollinger(data, 20, 2);
      const bbUpper = chart.addSeries(LineSeries, {
        color: "rgba(139, 92, 246, 0.5)",
        lineWidth: 1,
        lineStyle: 2,
        priceLineVisible: false,
        lastValueVisible: false,
      });
      const bbLower = chart.addSeries(LineSeries, {
        color: "rgba(139, 92, 246, 0.5)",
        lineWidth: 1,
        lineStyle: 2,
        priceLineVisible: false,
        lastValueVisible: false,
      });
      bbUpper.setData(bb.upper);
      bbLower.setData(bb.lower);
      overlaySeries.push(bbUpper, bbLower);
    }

    overlaySeriesRef.current = overlaySeries;
    chart.timeScale().fitContent();

    return () => {
      chart.remove();
      chartRef.current = null;
      overlaySeriesRef.current = [];
    };
  }, [data, height, activeOverlays]);

  const overlayButtons: { key: Overlay; label: string; color: string }[] = [
    { key: "sma20", label: "SMA 20", color: "#f59e0b" },
    { key: "sma50", label: "SMA 50", color: "#3b82f6" },
    { key: "bollinger", label: "Bollinger", color: "#8b5cf6" },
  ];

  return (
    <div className="rounded-[var(--radius-lg)] border border-[var(--color-border)] bg-[var(--color-surface)]">
      {/* Overlay toggles */}
      <div className="flex items-center gap-1.5 border-b border-[var(--color-border)] px-3 py-2">
        <span className="mr-1 text-[10px] uppercase tracking-wider text-[var(--color-muted)]">
          Overlays
        </span>
        {overlayButtons.map((o) => (
          <button
            key={o.key}
            type="button"
            onClick={() => toggleOverlay(o.key)}
            className={cn(
              "rounded-full border px-2.5 py-0.5 text-[10px] font-medium transition-colors",
              activeOverlays.has(o.key)
                ? "border-transparent text-white"
                : "border-[var(--color-border)] text-[var(--color-muted-strong)] hover:border-[var(--color-border-strong)]"
            )}
            style={
              activeOverlays.has(o.key)
                ? { backgroundColor: o.color }
                : undefined
            }
          >
            {o.label}
          </button>
        ))}
      </div>
      <div ref={containerRef} className="w-full p-3" style={{ height }} />
    </div>
  );
}
