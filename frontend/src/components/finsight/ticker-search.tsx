"use client";

import { useEffect, useRef, useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { ArrowRight, Loader2, Search, TrendingUp } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { api } from "@/lib/api";
import type { TickerHit } from "@/lib/schemas";

const POPULAR: TickerHit[] = [
  { ticker: "AAPL", name: "Apple Inc.", exchange: "Nasdaq", score: 0 },
  { ticker: "MSFT", name: "Microsoft Corp.", exchange: "Nasdaq", score: 0 },
  { ticker: "NVDA", name: "NVIDIA Corp.", exchange: "Nasdaq", score: 0 },
  { ticker: "TSLA", name: "Tesla, Inc.", exchange: "Nasdaq", score: 0 },
  { ticker: "GOOGL", name: "Alphabet Inc.", exchange: "Nasdaq", score: 0 },
  { ticker: "AMZN", name: "Amazon.com, Inc.", exchange: "Nasdaq", score: 0 },
];

interface TickerSearchProps {
  className?: string;
  autoFocus?: boolean;
  size?: "md" | "lg";
}

export function TickerSearch({
  className,
  autoFocus,
  size = "lg",
}: TickerSearchProps) {
  const router = useRouter();
  const [value, setValue] = useState("");
  const [hits, setHits] = useState<TickerHit[]>([]);
  const [open, setOpen] = useState(false);
  const [activeIdx, setActiveIdx] = useState(0);
  const [searching, setSearching] = useState(false);
  const [isPending, startTransition] = useTransition();
  const containerRef = useRef<HTMLDivElement>(null);
  const reqIdRef = useRef(0);

  // Debounced fetch
  useEffect(() => {
    const q = value.trim();
    if (q.length === 0) {
      setHits(POPULAR);
      setSearching(false);
      return;
    }
    setSearching(true);
    const myReqId = ++reqIdRef.current;
    const t = setTimeout(async () => {
      try {
        const results = await api.searchTickers(q, 8);
        if (reqIdRef.current === myReqId) {
          setHits(results);
          setActiveIdx(0);
        }
      } catch {
        if (reqIdRef.current === myReqId) setHits([]);
      } finally {
        if (reqIdRef.current === myReqId) setSearching(false);
      }
    }, 180);
    return () => clearTimeout(t);
  }, [value]);

  // Click-outside to close
  useEffect(() => {
    function onDoc(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, []);

  function go(ticker: string) {
    const t = ticker.trim().toUpperCase();
    if (!t) return;
    setOpen(false);
    startTransition(() => {
      router.push(`/workspace/${encodeURIComponent(t)}`);
    });
  }

  function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    // Prefer the highlighted suggestion if dropdown is open and has hits
    if (open && hits.length > 0) {
      go(hits[activeIdx]?.ticker ?? value);
    } else {
      go(value);
    }
  }

  function onKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (!open) return;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActiveIdx((i) => Math.min(i + 1, hits.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActiveIdx((i) => Math.max(i - 1, 0));
    } else if (e.key === "Escape") {
      setOpen(false);
    }
  }

  const heightClass = size === "lg" ? "h-16" : "h-12";
  const textClass = size === "lg" ? "text-xl" : "text-base";

  return (
    <div ref={containerRef} className={cn("relative w-full max-w-2xl", className)}>
      <form
        onSubmit={onSubmit}
        className={cn(
          "group relative flex items-center gap-2 rounded-[var(--radius-xl)] border border-[var(--color-border)] bg-[var(--color-surface)] pl-5 pr-2 transition-all duration-200 focus-within:border-[var(--color-accent)] focus-within:shadow-[0_0_0_4px_color-mix(in_oklab,var(--color-accent)_15%,transparent)]",
          heightClass,
        )}
      >
        {searching ? (
          <Loader2 className="h-5 w-5 shrink-0 animate-spin text-[var(--color-accent)]" />
        ) : (
          <Search className="h-5 w-5 shrink-0 text-[var(--color-muted)] group-focus-within:text-[var(--color-accent)] transition-colors" />
        )}
        <input
          autoFocus={autoFocus}
          value={value}
          onChange={(e) => {
            setValue(e.target.value);
            setOpen(true);
          }}
          onFocus={() => setOpen(true)}
          onKeyDown={onKeyDown}
          placeholder="Apple, NVIDIA, AAPL, tesla…"
          className={cn(
            "flex-1 bg-transparent outline-none text-[var(--color-foreground)] placeholder:text-[var(--color-muted)]",
            textClass,
          )}
          spellCheck={false}
          autoComplete="off"
        />
        <Button
          type="submit"
          variant="primary"
          size={size === "lg" ? "lg" : "md"}
          disabled={!value.trim() || isPending}
        >
          {isPending ? "Loading…" : "Analyze"}
          <ArrowRight className="h-4 w-4" />
        </Button>
      </form>

      {open && hits.length > 0 && (
        <div className="absolute left-0 right-0 z-50 mt-2 overflow-hidden rounded-[var(--radius-lg)] border border-[var(--color-border)] bg-[var(--color-surface-elevated)] shadow-2xl">
          {value.trim().length === 0 && (
            <div className="flex items-center gap-2 border-b border-[var(--color-border)] px-4 py-2 text-xs uppercase tracking-wider text-[var(--color-muted)]">
              <TrendingUp className="h-3.5 w-3.5" />
              Popular tickers
            </div>
          )}
          <ul role="listbox" className="max-h-80 overflow-y-auto">
            {hits.map((h, i) => (
              <li key={`${h.ticker}-${i}`}>
                <button
                  type="button"
                  onMouseEnter={() => setActiveIdx(i)}
                  onClick={() => go(h.ticker)}
                  className={cn(
                    "flex w-full items-center justify-between gap-3 px-4 py-2.5 text-left transition-colors",
                    i === activeIdx
                      ? "bg-[color:color-mix(in_oklab,var(--color-accent)_12%,transparent)]"
                      : "hover:bg-[var(--color-surface)]",
                  )}
                >
                  <div className="flex min-w-0 items-center gap-3">
                    <span className="shrink-0 rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] px-2 py-0.5 font-mono text-xs font-semibold text-[var(--color-foreground)]">
                      {h.ticker}
                    </span>
                    <span className="truncate text-sm text-[var(--color-foreground)]">
                      {h.name}
                    </span>
                  </div>
                  {h.exchange && (
                    <span className="hidden shrink-0 text-xs uppercase text-[var(--color-muted)] sm:inline">
                      {h.exchange}
                    </span>
                  )}
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}

      {open && !searching && value.trim().length >= 2 && hits.length === 0 && (
        <div className="absolute left-0 right-0 z-50 mt-2 rounded-[var(--radius-lg)] border border-[var(--color-border)] bg-[var(--color-surface-elevated)] px-4 py-3 text-sm text-[var(--color-muted-strong)] shadow-2xl">
          No matches for <span className="font-mono">{value}</span>. Press Enter to try anyway.
        </div>
      )}
    </div>
  );
}
