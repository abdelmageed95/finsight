"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { ArrowLeftRight, Loader2, Search } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { api } from "@/lib/api";
import type { TickerHit } from "@/lib/schemas";
import { cn } from "@/lib/utils";

/**
 * "Compare to…" button — opens a popover with ticker autocomplete. Selecting
 * a ticker navigates to /compare?a=<ticker>&b=<other>.
 */
export function CompareButton({ ticker }: { ticker: string }) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [value, setValue] = useState("");
  const [hits, setHits] = useState<TickerHit[]>([]);
  const [searching, setSearching] = useState(false);
  const reqIdRef = useRef(0);

  useEffect(() => {
    if (!open) return;
    const q = value.trim();
    if (q.length === 0) {
      setHits([]);
      return;
    }
    setSearching(true);
    const myReqId = ++reqIdRef.current;
    const t = setTimeout(async () => {
      try {
        const results = await api.searchTickers(q, 8);
        if (reqIdRef.current === myReqId) {
          setHits(results.filter((h) => h.ticker !== ticker.toUpperCase()));
        }
      } catch {
        if (reqIdRef.current === myReqId) setHits([]);
      } finally {
        if (reqIdRef.current === myReqId) setSearching(false);
      }
    }, 180);
    return () => clearTimeout(t);
  }, [value, open, ticker]);

  function pick(other: string) {
    const a = ticker.toUpperCase();
    const b = other.toUpperCase();
    setOpen(false);
    setValue("");
    router.push(`/compare?a=${encodeURIComponent(a)}&b=${encodeURIComponent(b)}`);
  }

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button variant="ghost" size="md" title={`Compare ${ticker} to another stock`}>
          <ArrowLeftRight className="h-4 w-4" />
          Compare to…
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-80 p-0" align="end">
        <div className="flex items-center gap-2 border-b border-[var(--color-border)] px-3 py-2">
          {searching ? (
            <Loader2 className="h-4 w-4 animate-spin text-[var(--color-accent)]" />
          ) : (
            <Search className="h-4 w-4 text-[var(--color-muted)]" />
          )}
          <input
            autoFocus
            value={value}
            onChange={(e) => setValue(e.target.value)}
            placeholder="Type a ticker or company…"
            className="flex-1 bg-transparent text-sm outline-none placeholder:text-[var(--color-muted)]"
            spellCheck={false}
            autoComplete="off"
          />
        </div>
        <ul className="max-h-72 overflow-y-auto">
          {hits.length === 0 && value.trim().length >= 2 && !searching && (
            <li className="px-4 py-3 text-xs text-[var(--color-muted)]">
              No matches. Try a different query.
            </li>
          )}
          {hits.length === 0 && value.trim().length < 2 && (
            <li className="px-4 py-3 text-xs text-[var(--color-muted)]">
              Start typing to find a peer to compare against {ticker}.
            </li>
          )}
          {hits.map((h, i) => (
            <li key={`${h.ticker}-${i}`}>
              <button
                type="button"
                onClick={() => pick(h.ticker)}
                className={cn(
                  "flex w-full items-center justify-between gap-3 px-3 py-2 text-left transition-colors",
                  "hover:bg-[var(--color-surface)]",
                )}
              >
                <div className="flex min-w-0 items-center gap-2">
                  <span className="shrink-0 rounded-md border border-[var(--color-border)] bg-[var(--color-surface-elevated)] px-1.5 py-0.5 font-mono text-[10px] font-semibold text-[var(--color-foreground)]">
                    {h.ticker}
                  </span>
                  <span className="truncate text-sm text-[var(--color-foreground)]">
                    {h.name}
                  </span>
                </div>
                {h.exchange && (
                  <span className="hidden shrink-0 text-[10px] uppercase text-[var(--color-muted)] sm:inline">
                    {h.exchange}
                  </span>
                )}
              </button>
            </li>
          ))}
        </ul>
      </PopoverContent>
    </Popover>
  );
}
