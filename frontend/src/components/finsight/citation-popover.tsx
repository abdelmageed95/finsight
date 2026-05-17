"use client";

import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { cn } from "@/lib/utils";
import type { ReportCitation } from "@/lib/schemas";

/**
 * A small `[N]` pill that opens a popover with the cited excerpt on click/hover.
 * Designed to be inlined inside flowing prose.
 */
export function CitationChip({
  index,
  citation,
  className,
}: {
  index: number;
  citation?: ReportCitation;
  className?: string;
}) {
  const docType = citation?.doc_type ?? "";
  const excerpt = citation?.excerpt ?? "";
  return (
    <Popover>
      <PopoverTrigger asChild>
        <button
          type="button"
          aria-label={`Source ${index}`}
          className={cn(
            "inline-flex h-[1.4em] min-w-[1.6em] items-center justify-center rounded-md border border-[var(--color-border)] bg-[var(--color-surface-elevated)] px-1 align-baseline font-mono text-[10px] font-semibold leading-none text-[var(--color-muted-strong)] transition-colors hover:border-[var(--color-accent)] hover:text-[var(--color-accent)]",
            className,
          )}
        >
          {index}
        </button>
      </PopoverTrigger>
      <PopoverContent className="w-80" align="start" sideOffset={4}>
        <div className="mb-2 flex items-center gap-2">
          <span className="font-mono text-[10px] uppercase tracking-wider text-[var(--color-muted)]">
            Source {index}
          </span>
          {docType && (
            <span className="rounded-full border border-[var(--color-border)] bg-[var(--color-surface)] px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide text-[var(--color-muted-strong)]">
              {docType}
            </span>
          )}
        </div>
        <p className="text-sm leading-relaxed text-[var(--color-foreground)]">
          {excerpt || "No excerpt available."}
        </p>
      </PopoverContent>
    </Popover>
  );
}

/**
 * Render plain text and replace bracketed-number references like `[1]`, `[2,3]`,
 * or `[1] [2]` with `CitationChip` popovers. Unknown indices fall back to the
 * raw text so we never lose information.
 */
export function CitationText({
  text,
  citations,
  className,
}: {
  text: string;
  citations?: ReportCitation[] | null;
  className?: string;
}) {
  if (!text) return null;

  const lookup = new Map<number, ReportCitation>();
  citations?.forEach((c, i) => {
    const idx = c.source_index ?? i + 1;
    lookup.set(idx, c);
  });

  // Match `[N]` or `[N, M]` (allow inner whitespace and commas).
  const re = /\[(\d+(?:\s*,\s*\d+)*)\]/g;
  const out: React.ReactNode[] = [];
  let lastIdx = 0;
  let match: RegExpExecArray | null;
  let key = 0;
  while ((match = re.exec(text)) !== null) {
    if (match.index > lastIdx) {
      out.push(text.slice(lastIdx, match.index));
    }
    const indices = match[1]
      .split(",")
      .map((s) => Number.parseInt(s.trim(), 10))
      .filter((n) => Number.isFinite(n));
    indices.forEach((n, i) => {
      out.push(
        <CitationChip
          key={`c-${key++}`}
          index={n}
          citation={lookup.get(n)}
          className={i > 0 ? "ml-0.5" : "ml-0.5"}
        />,
      );
    });
    lastIdx = match.index + match[0].length;
  }
  if (lastIdx < text.length) out.push(text.slice(lastIdx));

  return <span className={className}>{out}</span>;
}
