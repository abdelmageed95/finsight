"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "@/lib/api";
import type { AnalyzeCheck } from "@/lib/schemas";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { AgentProgressStrip, type AgentStage } from "./agent-progress-strip";

const PRESET_QUESTIONS = [
  "What are the main risks?",
  "Is this a good long-term investment?",
  "Summarize the latest 10-K",
  "How is revenue trending?",
];

export function AnalyzeDialog({
  ticker,
  children,
  onComplete,
  defaultQuestion,
}: {
  ticker: string;
  children: React.ReactNode;
  onComplete?: (jobId: string) => void;
  defaultQuestion?: string;
}) {
  const [open, setOpen] = useState(false);
  const [question, setQuestion] = useState(defaultQuestion ?? PRESET_QUESTIONS[0]);

  // When a different default question flows in (e.g. user clicks a hero chip),
  // sync it into local state — but only while the dialog is closed, so we
  // never overwrite what the user is typing.
  useEffect(() => {
    if (defaultQuestion && !open) setQuestion(defaultQuestion);
  }, [defaultQuestion, open]);
  const [stage, setStage] = useState<AgentStage>("idle");
  const [error, setError] = useState<string | null>(null);
  const [existing, setExisting] = useState<AnalyzeCheck | null>(null);
  const [checkingExisting, setCheckingExisting] = useState(false);
  const [progressMsg, setProgressMsg] = useState<string>("");
  const [progressPct, setProgressPct] = useState<number>(0);
  const [partialSummary, setPartialSummary] = useState<string>("");
  const router = useRouter();
  const qc = useQueryClient();

  function stageFromKey(key: string): AgentStage {
    if (key === "data") return "data";
    if (key === "rag") return "rag";
    if (key === "report") return "report";
    return "idle";
  }

  // Check for existing analysis when dialog opens
  useEffect(() => {
    if (!open || !ticker) return;
    setCheckingExisting(true);
    api.checkExisting(ticker)
      .then((res) => setExisting(res))
      .catch(() => setExisting(null))
      .finally(() => setCheckingExisting(false));
  }, [open, ticker]);

  async function runAnalysis() {
    setError(null);
    setStage("data");
    setProgressMsg("Submitting analysis…");
    setProgressPct(2);
    setPartialSummary("");
    setExisting(null);

    let jobId: string | null = null;
    try {
      const res = await api.analyze(ticker, question);
      jobId = res.job_id;

      // Subscribe to live SSE progress. If the stream errors, we fall back
      // to polling below.
      let streamErrored = false;
      try {
        await api.streamAnalyzeProgress(jobId, {
          onProgress: (e) => {
            setStage(stageFromKey(e.stage));
            setProgressMsg(e.message);
            setProgressPct(e.percent);
          },
          onPartial: (e) => {
            if (e.summary) setPartialSummary(e.summary);
          },
          onDone: () => {
            setStage("done");
            setProgressPct(100);
            setProgressMsg("Analysis complete.");
          },
          onError: (msg) => {
            streamErrored = true;
            setError(msg || "Analysis failed.");
          },
        });
      } catch {
        streamErrored = true;
      }

      // If SSE failed mid-flight, poll once to pick up the final state
      if (streamErrored && jobId) {
        const rep = await api.report(jobId);
        if (rep.status === "failed") throw new Error("Analysis failed. Try again.");
      }

      qc.invalidateQueries({ queryKey: ["history"] });
      qc.invalidateQueries({ queryKey: ["history", ticker] });
      qc.invalidateQueries({ queryKey: ["ticker", ticker] });
      qc.invalidateQueries({ queryKey: ["conversations"] });

      setTimeout(() => {
        setOpen(false);
        if (onComplete && jobId) onComplete(jobId);
        else if (jobId) router.push(`/workspace/${ticker}?tab=research&job=${jobId}`);
        else router.push(`/workspace/${ticker}`);
      }, 800);
    } catch (e) {
      const msg =
        e instanceof ApiError
          ? `API ${e.status}: ${typeof e.body === "object" ? JSON.stringify(e.body) : e.message}`
          : e instanceof Error
          ? e.message
          : "Unknown error";
      setError(msg);
      setStage("idle");
    }
  }

  function viewExisting() {
    if (existing?.job_id) {
      setOpen(false);
      router.push(`/workspace/${ticker}?tab=research&job=${existing.job_id}`);
    }
  }

  function goToDashboard() {
    setOpen(false);
    router.push(`/workspace/${ticker}`);
  }

  function goToChat() {
    setOpen(false);
    router.push(`/workspace/${ticker}?tab=chat`);
  }

  return (
    <Dialog open={open} onOpenChange={(v) => { setOpen(v); if (!v) { setStage("idle"); setError(null); setExisting(null); setProgressMsg(""); setProgressPct(0); setPartialSummary(""); }}}>
      <DialogTrigger asChild>{children}</DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Analyze — {ticker}</DialogTitle>
          <DialogDescription>
            {existing?.exists
              ? `${ticker} has already been analyzed. You can view the existing results or run a fresh analysis.`
              : "The multi-agent pipeline will fetch data, retrieve relevant 10-K passages, and synthesize a cited report."}
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          {/* Existing analysis card */}
          {existing?.exists && stage === "idle" && (
            <div className="rounded-[var(--radius-md)] border border-[var(--color-accent)]/30 bg-[var(--color-accent)]/5 p-4 space-y-3">
              <p className="text-sm font-medium text-[var(--color-foreground)]">
                Existing analysis found
              </p>
              {existing.summary_preview && (
                <p className="text-xs text-[var(--color-muted-strong)] line-clamp-2">
                  {existing.summary_preview}…
                </p>
              )}
              <div className="flex flex-wrap gap-2">
                <Button variant="primary" size="sm" onClick={goToDashboard}>
                  View dashboard
                </Button>
                <Button variant="secondary" size="sm" onClick={viewExisting}>
                  View report
                </Button>
                <Button variant="secondary" size="sm" onClick={goToChat}>
                  Open chat
                </Button>
              </div>
            </div>
          )}

          {/* Analysis form */}
          {stage === "idle" && (
            <>
              <div className="flex flex-wrap gap-2">
                {PRESET_QUESTIONS.map((q) => (
                  <button
                    key={q}
                    type="button"
                    onClick={() => setQuestion(q)}
                    className={`rounded-full border px-3 py-1 text-xs transition-colors ${
                      question === q
                        ? "border-[var(--color-accent)] bg-[color:color-mix(in_oklab,var(--color-accent)_10%,transparent)] text-[var(--color-accent)]"
                        : "border-[var(--color-border)] text-[var(--color-muted-strong)] hover:border-[var(--color-border-strong)]"
                    }`}
                  >
                    {q}
                  </button>
                ))}
              </div>

              <Input
                value={question}
                onChange={(e) => setQuestion(e.target.value)}
                placeholder="Or type your own question…"
              />
            </>
          )}

          {stage !== "idle" && (
            <div className="space-y-3 rounded-[var(--radius-md)] border border-[var(--color-border)] bg-[var(--color-surface)] p-4">
              <AgentProgressStrip stage={stage} />
              {progressMsg && (
                <p className="text-sm text-[var(--color-foreground)]">
                  {progressMsg}
                </p>
              )}
              <div className="h-1.5 w-full overflow-hidden rounded-full bg-[var(--color-border)]">
                <div
                  className="h-full bg-[var(--color-accent)] transition-[width] duration-500 ease-out"
                  style={{ width: `${Math.max(2, Math.min(100, progressPct))}%` }}
                />
              </div>
              {partialSummary && (
                <div className="rounded-md border border-[var(--color-border)] bg-[var(--color-background)] p-3">
                  <div className="mb-1 text-xs uppercase tracking-wider text-[var(--color-muted)]">
                    Preview
                  </div>
                  <p className="text-sm leading-relaxed text-[var(--color-foreground)]">
                    {partialSummary}
                  </p>
                </div>
              )}
              <p className="text-xs text-[var(--color-muted)]">
                This typically takes 20–60 seconds for a fresh ticker.
              </p>
            </div>
          )}

          {error && (
            <div className="rounded-[var(--radius-md)] border border-[color:color-mix(in_oklab,var(--color-danger)_40%,transparent)] bg-[color:color-mix(in_oklab,var(--color-danger)_10%,transparent)] p-3 text-xs text-[var(--color-danger)]">
              {error}
            </div>
          )}

          <div className="flex items-center justify-end gap-2">
            <Button variant="ghost" onClick={() => setOpen(false)} disabled={stage !== "idle" && stage !== "done"}>
              Cancel
            </Button>
            <Button
              variant="primary"
              onClick={runAnalysis}
              disabled={!question.trim() || (stage !== "idle" && stage !== "done") || checkingExisting}
            >
              {existing?.exists ? "Re-analyze (overwrite)" : stage === "idle" ? "Run analysis" : stage === "done" ? "Done" : "Running…"}
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
