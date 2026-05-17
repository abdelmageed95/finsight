import { cn } from "@/lib/utils";
import { Check, Loader2 } from "lucide-react";

export type AgentStage = "idle" | "data" | "rag" | "report" | "done";

const STAGES: { key: AgentStage; label: string }[] = [
  { key: "data", label: "Fethching Data" },
  { key: "rag", label: "Preparing Data" },
  { key: "report", label: "Generating Report" },
];

const ORDER: AgentStage[] = ["idle", "data", "rag", "report", "done"];

export function AgentProgressStrip({
  stage,
  className,
}: {
  stage: AgentStage;
  className?: string;
}) {
  const idx = ORDER.indexOf(stage);
  return (
    <div className={cn("flex items-center gap-3 text-xs", className)}>
      {STAGES.map((s, i) => {
        const stageIdx = ORDER.indexOf(s.key);
        const isDone = idx > stageIdx;
        const isActive = idx === stageIdx;
        return (
          <div key={s.key} className="flex items-center gap-3">
            <div
              className={cn(
                "flex items-center gap-1.5 transition-colors",
                isDone
                  ? "text-[var(--color-accent)]"
                  : isActive
                  ? "text-[var(--color-foreground)]"
                  : "text-[var(--color-muted)]"
              )}
            >
              {isDone ? (
                <Check className="h-3.5 w-3.5" />
              ) : isActive ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <span className="h-1.5 w-1.5 rounded-full bg-[var(--color-muted)]" />
              )}
              {s.label}
            </div>
            {i < STAGES.length - 1 && (
              <span
                className={cn(
                  "h-px w-6 transition-colors",
                  idx > stageIdx
                    ? "bg-[var(--color-accent)]"
                    : "bg-[var(--color-border)]"
                )}
              />
            )}
          </div>
        );
      })}
    </div>
  );
}
